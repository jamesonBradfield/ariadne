import json
import logging
import os
import re
import textgrad as tg
from typing import Any, Dict, List, Tuple

# Set environment variables for LiteLLM
os.environ["OPENAI_API_BASE"] = "http://100.92.54.124:8080/v1"
os.environ["OPENAI_API_KEY"] = "sk-no-key"

from ariadne.components import SyntaxGate
from ariadne.profiles.rust_profile import RustProfile

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ariadne.optimizer")

class EngineWrapper:
    """
    Wraps the TextGrad engine to handle thinking tokens and enforce formatting tags.
    """
    def __init__(self, engine, tags):
        self.engine = engine
        self.tags = tags

    def __call__(self, prompt, **kwargs):
        response = self.engine(prompt, **kwargs)
        # 1. Strip thinking tokens (common in Qwen)
        response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
        response = re.sub(r"^</think>", "", response).strip()
        
        # 2. Enforce TextGrad tags if missing
        if self.tags[0] not in response:
            logger.warning(f"Engine output missing tags {self.tags[0]}. Wrapping response manually.")
            response = f"{self.tags[0]}\n{response}\n{self.tags[1]}"
            
        return response

    def generate(self, *args, **kwargs):
        return self.__call__(*args, **kwargs)

class MapsLoss(tg.loss.Module):
    """
    Custom Loss Function for MAPS state.
    Evaluates LLM output via SyntaxGate and index validation.
    """
    def __init__(self, language_ptr):
        super().__init__()
        self.syntax_gate = SyntaxGate(language_ptr)

    def forward(self, response_variable: tg.Variable, context: Dict[str, Any]) -> tg.Variable:
        response_text = response_variable.value
        children_view_str = context.get("children_view", "")
        
        # 1. Parse JSON
        try:
            start_index = response_text.find("{")
            end_index = response_text.rfind("}")
            if start_index == -1 or end_index == -1:
                return tg.Variable(
                    "CRITICAL FAILURE: The model did not output any JSON object. "
                    "The system prompt MUST strictly command the model to output ONLY a raw JSON object and forbid markdown or conversational text.",
                    role_description="feedback"
                )
            
            json_str = response_text[start_index : end_index + 1]
            data = json.loads(json_str)
        except Exception as e:
            return tg.Variable(
                f"JSON PARSE FAILURE: The model produced invalid JSON (Error: {str(e)}). "
                f"The system prompt needs to be extremely explicit about formatting. It must demand a perfectly formatted JSON object with double quotes for keys and no trailing commas.",
                role_description="feedback"
            )

        action = data.get("action")
        target_idx = data.get("target")
        code = data.get("code", "")

        feedback = []

        # 2. Check Syntax
        if action in ["replace", "insert_before", "insert_after"]:
            res = self.syntax_gate.validate(code)
            if not res["valid"]:
                feedback.append(
                    f"SYNTAX ERROR: The code snippet provided by the model is invalid.\n"
                    f"Error: {res['error_message']}\n"
                    f"Code: {code}\n"
                    f"The system prompt MUST remind the model to generate syntactically correct code for the language being edited."
                )

        # 3. Check Index Bounds
        import re
        indices = re.findall(r"\[(\d+)\]", children_view_str)
        max_idx = max(int(i) for i in indices) if indices else -1
        
        if target_idx is not None:
            if target_idx < 0 or target_idx > max_idx:
                feedback.append(
                    f"INDEX ERROR: Target index {target_idx} is out of bounds (max index: {max_idx}). "
                    f"The system prompt should instruct the model to only use the target IDs provided in the 'Children View'."
                )
        elif action != "done" and action != "up":
            feedback.append("VALIDATION ERROR: 'target' index is missing. The prompt must enforce that 'target' is required for editing actions.")

        if not feedback:
            return tg.Variable("SUCCESS: The output is valid, syntactically correct, and follows all rules.", role_description="feedback")
        
        return tg.Variable("\n".join(feedback), role_description="feedback")

def run_optimization():
    with open("ariadne_config.json", "r") as f:
        config = json.load(f)
    
    maps_config = config["states"]["MAPS"]
    initial_system = maps_config["system_prompt"]
    initial_user = maps_config["user_prompt_template"]

    from textgrad.engine import LiteLLMEngine
    raw_engine = LiteLLMEngine(model_string="openai/qwen")
    
    tags = ["<IMPROVED_VARIABLE>", "</IMPROVED_VARIABLE>"]
    engine = EngineWrapper(raw_engine, tags)
    tg.set_backward_engine(engine)

    system_prompt = tg.Variable(
        initial_system, 
        requires_grad=True, 
        role_description="system prompt for the Micro AST Procedural Surgeon (MAPS) state"
    )

    # ADDING CONSTRAINTS to prevent the model from forgetting the JSON format
    constraints = [
        "The prompt MUST explicitly state that the output should be ONLY a SINGLE JSON object, with no markdown formatting.",
        "The prompt MUST explicitly list the valid actions: 'zoom', 'up', 'replace', 'insert_before', 'insert_after', 'delete', 'done'.",
        "The prompt MUST provide the exact JSON schema to follow: {\"reasoning\": \"...\", \"action\": \"...\", \"target\": 0, \"code\": \"...\"}."
    ]

    optimizer = tg.TGD(parameters=[system_prompt], new_variable_tags=tags, constraints=constraints)
    model = tg.BlackboxLLM(system_prompt=system_prompt, engine=engine)

    profile = RustProfile()
    lang_ptr = profile.get_language_ptr()
    
    sample_inputs = [
        {
            "intent": "Change field 'hp' to 'health'",
            "error_context": "error[E0609]: no field `hp` on type `Entity`",
            "current_symbol": "Entity",
            "current_node_type": "struct_item",
            "children_view": "[0] field_declaration:\npub health: f32,\n"
        },
        {
            "intent": "Remove unused parameter",
            "error_context": "warning: unused variable: `x`",
            "current_symbol": "my_func",
            "current_node_type": "function_item",
            "children_view": "[0] parameter:\nx: i32\n[1] parameter:\ny: i32\n"
        },
        {
            "intent": "Add missing semicolon",
            "error_context": "error: expected `;`, found `}`",
            "current_symbol": "fix_me",
            "current_node_type": "function_item",
            "children_view": "[0] expression_statement:\nlet a = 1\n"
        },
        {
            "intent": "Fix typo in method call",
            "error_context": "error[E0599]: no method named `prntln` found for struct `Stdout`",
            "current_symbol": "run",
            "current_node_type": "function_item",
            "children_view": "[0] expression_statement:\nio::stdout().prntln(\"hi\")\n"
        },
        {
            "intent": "Correct return type",
            "error_context": "error[E0308]: mismatched types. expected `i32`, found `f32`",
            "current_symbol": "get_val",
            "current_node_type": "function_item",
            "children_view": "[0] type_identifier:\nf32\n"
        }
    ]

    loss_fn = MapsLoss(lang_ptr)

    for epoch in range(2): # Reduced to 2 epochs since we have strong constraints now
        logger.info(f"=== Starting Epoch {epoch + 1} ===")
        
        for idx, input_data in enumerate(sample_inputs):
            optimizer.zero_grad()
            
            rendered_user = initial_user \
                .replace("{{intent}}", input_data["intent"]) \
                .replace("{{error_context}}", input_data["error_context"]) \
                .replace("{{current_symbol}}", input_data["current_symbol"]) \
                .replace("{{current_node_type}}", input_data["current_node_type"]) \
                .replace("{{children_view}}", input_data["children_view"])
            
            user_input_var = tg.Variable(
                rendered_user, 
                role_description="user input containing the intent, error context, and AST children view"
            )
            
            logger.info(f"Processing input {idx + 1}...")
            
            response = model(user_input_var)
            loss = loss_fn(response, input_data)
            logger.info(f"Input {idx + 1} Loss/Feedback: {loss.value}")
            
            loss.backward()
            optimizer.step()
            
            logger.info(f"Finished processing input {idx + 1}")

    print("\n--- Optimization Complete ---")
    print(f"Optimized System Prompt:\n{system_prompt.value}")

if __name__ == "__main__":
    run_optimization()
