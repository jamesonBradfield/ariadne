import json
import os
import textgrad as tg
from textgrad.engine import get_engine

def load_config():
    with open("ariadne_config.json", "r") as f:
        return json.load(f)

def save_config(config):
    with open("ariadne_config.json", "w") as f:
        json.dump(config, f, indent=2)

def load_cases():
    with open("tests/llm_cases.json", "r") as f:
        return json.load(f)

def optimize():
    # Setup TextGrad engine using LiteLLM/OpenAI compatible local or remote server
    # We will use the config's model if possible, but for textgrad we might need a strong judge
    # Assuming textgrad works with litellm setup
    tg.set_backward_engine("gpt-4o", override=True) # Use a strong model for backprop/gradients if available, or fall back
    
    config = load_config()
    cases = load_cases()

    print("Running TextGrad Optimization on MAPS Prompts...")

    for case in cases:
        state_name = case["state"]
        print(f"\n--- Evaluating Case: {case['id']} ({state_name}) ---")
        
        state_config = config["states"][state_name]
        
        # Define the variable to optimize
        system_prompt_var = tg.Variable(
            state_config["system_prompt"], 
            role_description="The system prompt instructing the AI on how to navigate or edit the AST",
            requires_grad=True
        )

        # We construct the input for the specific state
        user_prompt_template = state_config["user_prompt_template"]
        
        # Simple template rendering
        user_prompt_text = user_prompt_template
        for key, value in case.items():
            if f"{{{{{key}}}}}" in user_prompt_text:
                user_prompt_text = user_prompt_text.replace(f"{{{{{key}}}}}", str(value))
                
        # Handle cases where error_context isn't replaced because it's not in the case dict directly as a template key sometimes
        if "{{error_context}}" in user_prompt_text:
            user_prompt_text = user_prompt_text.replace("{{error_context}}", case.get("error_context", ""))

        input_var = tg.Variable(user_prompt_text, role_description="The current state of the AST and user intent")

        # The model we are evaluating
        model = tg.BlackboxLLM(engine=tg.get_engine("gpt-4o")) # Ideally we use the target model, but for optimization gpt-4o is standard

        # Forward pass
        prediction = model(tg.messages.chat([
            tg.messages.SystemMessage(system_prompt_var),
            tg.messages.UserMessage(input_var)
        ]))

        print(f"Prediction: {prediction.value}")

        # Define the evaluation criteria based on expected vs anti-expected
        expected = case.get("expected_action") or case.get("expected_symbol_target")
        anti_expected = case.get("anti_expected_action") or case.get("anti_expected_symbol_target")

        eval_instruction = f"Evaluate if the prediction correctly chooses the action or target '{expected}'. It MUST NOT choose '{anti_expected}'. If it chose the wrong one, provide a gradient to fix the system prompt to explicitly forbid that failure mode."
        
        evaluator = tg.LLMEvaluator(eval_instruction=eval_instruction, engine=tg.get_engine("gpt-4o"))
        
        loss = evaluator(prediction)
        print(f"Loss/Feedback: {loss.value}")

        if loss.value.lower().startswith("pass") or "correct" in loss.value.lower():
            print("Case passed. No optimization needed.")
            continue

        print("Optimizing system prompt...")
        
        # Optimizer
        optimizer = tg.TGD(parameters=[system_prompt_var])
        loss.backward()
        optimizer.step()

        print(f"\nOptimized System Prompt:\n{system_prompt_var.value}")
        
        # Update config
        config["states"][state_name]["system_prompt"] = system_prompt_var.value
        save_config(config)
        print(f"Updated ariadne_config.json for {state_name}")

if __name__ == "__main__":
    optimize()
