import json
import logging
import os
from typing import Any, Dict, List, Tuple

# Mocking textgrad if not installed for the sake of drafting the script
try:
    import textgrad as tg
except ImportError:
    # This is just to allow the script to be 'created' and 'read' without errors in the CLI
    # In a real run, the user would pip install it.
    class tg:
        class Variable:
            def __init__(self, value, requires_grad=False, role_description=""):
                self.value = value
        class Module: pass
        class TGD:
            def __init__(self, parameters): pass
            def zero_grad(self): pass
            def step(self): pass

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
        # children_view is formatted as "[0] type:\ncode\n[1] type:\ncode"
        # We can count the number of "[idx]" to find the max index.
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

    # 2. Define Variables to optimize
    system_prompt = tg.Variable(
        initial_system, 
        requires_grad=True, 
        role_description="system prompt for the MAPS state"
    )
    user_prompt_template = tg.Variable(
        initial_user, 
        requires_grad=True, 
        role_description="user prompt template for the MAPS state"
    )

    # 3. Setup Optimizer
    optimizer = tg.TGD(parameters=[system_prompt, user_prompt_template])

    # 4. Dataset (5 sample inputs)
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

    # 5. Loss Function
    loss_fn = MapsLoss(lang_ptr)

    # 6. Optimization Loop
    # In a real run, we would use an actual LLM engine here.
    # engine = tg.engines.LiteLLM(model="gpt-4o")
    
    for epoch in range(3): # Run 3 epochs over the dataset
        logger.info(f"Starting Epoch {epoch + 1}")
        
        for idx, input_data in enumerate(sample_inputs):
            optimizer.zero_grad()
            
            # Forward: Render prompt and call LLM
            # (In reality, we would use a tg.Module to wrap the LLM call)
            # For this draft, we show the conceptual flow
            
            # rendered_user = initial_user.replace("{{intent}}", input_data["intent"])...
            # response = engine(system_prompt, rendered_user)
            
            # loss = loss_fn(response, input_data)
            # loss.backward()
            # optimizer.step()
            
            logger.info(f"Processed input {idx + 1}")

    print("Optimization Complete.")
    print(f"Optimized System Prompt: {system_prompt.value}")
    print(f"Optimized User Prompt Template: {user_prompt_template.value}")

if __name__ == "__main__":
    run_optimization()
