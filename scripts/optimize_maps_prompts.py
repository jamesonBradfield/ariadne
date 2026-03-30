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
    Custom Loss Function for MAPS state using Markdown SEARCH/REPLACE blocks.
    Evaluates LLM output via existence of blocks and matching content.
    """
    def __init__(self, language_ptr):
        super().__init__()
        self.syntax_gate = SyntaxGate(language_ptr)

    def forward(self, response_variable: tg.Variable, context: Dict[str, Any]) -> tg.Variable:
        response_text = response_variable.value
        node_text = context.get("node_text", "")
        
        # 1. Extract SEARCH/REPLACE blocks
        search_pattern = r"<<<<\n(.*?)\n====\n(.*?)\n>>>>"
        matches = re.findall(search_pattern, response_text, re.DOTALL)
        
        if not matches:
            return tg.Variable(
                "CRITICAL FAILURE: No SEARCH/REPLACE block found. "
                "The output MUST contain a block starting with '<<<<', separated by '====', and ending with '>>>>'. "
                "Ensure the block is formatted exactly as specified in the system prompt.",
                role_description="feedback"
            )

        feedback = []
        
        for search_text, replace_text in matches:
            # 2. Check if SEARCH text exists in node_text
            if search_text not in node_text:
                feedback.append(
                    f"SEARCH ERROR: The SEARCH block text was not found exactly within the target code. "
                    f"Expected substring:\n{search_text}\n"
                    f"Actual target code:\n{node_text}\n"
                    f"The model must copy the code EXACTLY, including all whitespace, indentation, and comments."
                )

            # 3. Check Syntax of REPLACE text (optional/best-effort)
            # Since replace_text might be a fragment, we'll try to validate it in context
            # but for now, we just check if it's empty when it shouldn't be.
            if not replace_text.strip() and search_text.strip():
                 # This might be a deletion, which is valid, but let's warn if intent wasn't deletion
                 if "remove" not in context.get("intent", "").lower() and "delete" not in context.get("intent", "").lower():
                     feedback.append("WARNING: REPLACE block is empty but intent does not seem to be deletion.")

        if not feedback:
            return tg.Variable("SUCCESS: The output contains a valid SEARCH/REPLACE block that matches the target code.", role_description="feedback")
        
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

    # UPDATED CONSTRAINTS for SEARCH/REPLACE
    constraints = [
        "The prompt MUST explicitly state the SEARCH/REPLACE format: <<<<, ====, >>>>.",
        "The prompt MUST emphasize that the SEARCH block MUST match the target code EXACTLY, bit-for-bit.",
        "The prompt MUST forbid JSON output.",
        "The prompt SHOULD suggest including some context lines in the SEARCH block to ensure uniqueness."
    ]

    optimizer = tg.TGD(parameters=[system_prompt], new_variable_tags=tags, constraints=constraints)
    model = tg.BlackboxLLM(system_prompt=system_prompt, engine=engine)

    profile = RustProfile()
    lang_ptr = profile.get_language_ptr()
    
    sample_inputs = [
        {
            "intent": "Rename field 'hp' to 'health'",
            "error_context": "error[E0609]: no field `hp` on type `Entity`",
            "current_symbol": "Entity",
            "current_node_type": "struct_item",
            "node_text": "pub struct Entity {\n    pub hp: f32,\n    pub x: f32,\n    pub y: f32,\n}"
        },
        {
            "intent": "Fix typo in println! macro",
            "error_context": "error: cannot find macro `prntln` in this scope",
            "current_symbol": "main",
            "current_node_type": "function_item",
            "node_text": "fn main() {\n    prntln!(\"Hello, world!\");\n}"
        },
        {
            "intent": "Add missing return type i32",
            "error_context": "error[E0308]: mismatched types. expected `i32`, found `()` ",
            "current_symbol": "add",
            "current_node_type": "function_item",
            "node_text": "fn add(a: i32, b: i32) {\n    a + b\n}"
        },
        {
            "intent": "Change parameter type from i32 to f32",
            "error_context": "error[E0308]: mismatched types. expected `f32`, found `i32`",
            "current_symbol": "sqrt",
            "current_node_type": "function_item",
            "node_text": "fn sqrt(val: i32) -> f32 {\n    val.sqrt()\n}"
        },
        {
            "intent": "Publicize the struct",
            "error_context": "error[E0603]: struct `Data` is private",
            "current_symbol": "Data",
            "current_node_type": "struct_item",
            "node_text": "struct Data {\n    value: i32,\n}"
        }
    ]

    loss_fn = MapsLoss(lang_ptr)

    for epoch in range(2): 
        logger.info(f"=== Starting Epoch {epoch + 1} ===")
        
        for idx, input_data in enumerate(sample_inputs):
            optimizer.zero_grad()
            
            rendered_user = initial_user \
                .replace("{{intent}}", input_data["intent"]) \
                .replace("{{error_context}}", input_data["error_context"]) \
                .replace("{{current_symbol}}", input_data["current_symbol"]) \
                .replace("{{current_node_type}}", input_data["current_node_type"]) \
                .replace("{{node_text}}", input_data["node_text"])
            
            user_input_var = tg.Variable(
                rendered_user, 
                role_description="user input containing the intent, error context, and target code"
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
    
    # Optional: Write the optimized prompt back to config?
    # No, better let the user decide.

if __name__ == "__main__":
    run_optimization()
