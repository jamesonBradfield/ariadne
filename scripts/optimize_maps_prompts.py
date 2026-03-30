import json
import logging
import os
import textgrad as tg
from typing import Any, Dict, List, Tuple

from ariadne.components import SyntaxGate
from ariadne.profiles.rust_profile import RustProfile

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ariadne.optimizer")

class MapsLoss(tg.Module):
    """
    Custom Loss Function for MAPS state.
    Evaluates LLM output via SyntaxGate and index validation.
    """
    def __init__(self, language_ptr):
        super().__init__()
        self.syntax_gate = SyntaxGate(language_ptr)

    def forward(self, response_variable: tg.Variable, context: Dict[str, Any]) -> tg.Variable:
        """
        Calculates 'textual gradient' (feedback) for the LLM response.
        """
        response_text = response_variable.value
        children_view_str = context.get("children_view", "")
        
        # 1. Parse JSON
        try:
            # We use a robust extraction similar to Ariadne's QueryLLM
            import re
            start_index = response_text.find("{")
            end_index = response_text.rfind("}")
            if start_index == -1 or end_index == -1:
                return tg.Variable(
                    "CRITICAL FAILURE: Output is not valid JSON. You MUST output a single JSON object.",
                    role_description="feedback"
                )
            
            json_str = response_text[start_index : end_index + 1]
            data = json.loads(json_str)
        except Exception as e:
            return tg.Variable(
                f"FAILURE: Failed to parse JSON: {str(e)}. Ensure your output is perfectly formatted JSON.",
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
                    f"SYNTAX ERROR: The code snippet you provided is invalid.\n"
                    f"Error: {res['error_message']}\n"
                    f"Code: {code}"
                )

        # 3. Check Index Bounds
        import re
        indices = re.findall(r"\[(\d+)\]", children_view_str)
        max_idx = max(int(i) for i in indices) if indices else -1
        
        if target_idx is not None:
            if target_idx < 0 or target_idx > max_idx:
                feedback.append(
                    f"INDEX ERROR: Target index {target_idx} is out of bounds for the current view (max index: {max_idx})."
                )
        elif action != "done" and action != "up":
            feedback.append("VALIDATION ERROR: 'target' index is missing for action that requires it.")

        if not feedback:
            return tg.Variable("SUCCESS: The output is valid and follows all rules.", role_description="feedback")
        
        return tg.Variable("\n".join(feedback), role_description="feedback")

def run_optimization():
    # 1. Load initial prompts from config
    with open("ariadne_config.json", "r") as f:
        config = json.load(f)
    
    maps_config = config["states"]["MAPS"]
    initial_system = maps_config["system_prompt"]
    initial_user = maps_config["user_prompt_template"]

    # 2. Setup the TextGrad engine pointing to the local llama.cpp server
    engine = tg.get_engine(
        engine_name="openai/qwen",
        api_base="http://localhost:8080/v1",
        api_key="sk-no-key"
    )
    
    # TextGrad typically uses either set_backward_engine or set_default_engine
    try:
        tg.set_default_engine(engine)
    except AttributeError:
        pass
    try:
        tg.set_backward_engine(engine)
    except AttributeError:
        pass

    # 3. Define the system prompt Variable to optimize
    system_prompt = tg.Variable(
        initial_system, 
        requires_grad=True, 
        role_description="system prompt for the Micro AST Procedural Surgeon (MAPS) state"
    )

    # 4. Setup Optimizer
    # We focus on optimizing the system prompt here as the user prompt is mostly contextual template variables.
    optimizer = tg.TGD(parameters=[system_prompt])

    # 5. Initialize the BlackboxLLM wrapper for the forward pass
    model = tg.BlackboxLLM(system_prompt=system_prompt, engine=engine)

    # 6. Dataset (5 sample inputs)
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

    # 7. Loss Function
    loss_fn = MapsLoss(lang_ptr)

    # 8. Optimization Loop
    for epoch in range(3): # Run 3 epochs over the dataset
        logger.info(f"=== Starting Epoch {epoch + 1} ===")
        
        for idx, input_data in enumerate(sample_inputs):
            optimizer.zero_grad()
            
            # Format the user prompt manually
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
            
            # Forward pass: Generate the LLM response
            response = model(user_input_var)
            
            # Calculate the loss / feedback
            loss = loss_fn(response, input_data)
            logger.info(f"Input {idx + 1} Loss/Feedback: {loss.value}")
            
            # Backward pass: Generate textual gradients based on the feedback
            loss.backward()
            
            # Optimization step: Ask the LLM to update the system prompt based on criticisms
            optimizer.step()
            
            logger.info(f"Finished processing input {idx + 1}")

    print("\n--- Optimization Complete ---")
    print(f"Optimized System Prompt:\n{system_prompt.value}")

if __name__ == "__main__":
    run_optimization()
