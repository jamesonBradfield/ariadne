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
    config = load_config()
    cases = load_cases()
    
    # 1. Setup local TextGrad engine using Ariadne's configuration
    default_cfg = config.get("default", {})
    api_base = default_cfg.get("api_base", "http://localhost:8080/v1")
    model_name = default_cfg.get("model", "openai/llama-cpp")
    
    # TextGrad uses litellm internally. We configure it via ChatExternalClient
    # to target our local llama-cpp endpoint.
    engine = tg.engines.ChatExternalClient(
        model_string=model_name,
        base_url=api_base,
        api_key="none"
    )
    
    # Set the local engine for both forward and backward passes
    tg.set_backward_engine(engine, override=True)
    
    print(f"Running TextGrad Optimization using Local Endpoint: {api_base} ({model_name})")

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
        
        user_prompt_text = user_prompt_template
        for key, value in case.items():
            if f"{{{{{key}}}}}" in user_prompt_text:
                user_prompt_text = user_prompt_text.replace(f"{{{{{key}}}}}", str(value))
                
        if "{{error_context}}" in user_prompt_text:
            user_prompt_text = user_prompt_text.replace("{{error_context}}", case.get("error_context", ""))

        input_var = tg.Variable(user_prompt_text, role_description="The current state of the AST and user intent")

        # Use local engine for the model
        model = tg.BlackboxLLM(engine=engine)

        # Forward pass
        prediction = model(tg.messages.chat([
            tg.messages.SystemMessage(system_prompt_var),
            tg.messages.UserMessage(input_var)
        ]))

        print(f"Prediction: {prediction.value}")

        # Define the evaluation criteria
        expected = case.get("expected_action") or case.get("expected_symbol_target")
        anti_expected = case.get("anti_expected_action") or case.get("anti_expected_symbol_target")

        eval_instruction = f"Evaluate if the prediction correctly chooses the action or target '{expected}'. It MUST NOT choose '{anti_expected}'. If it chose the wrong one, provide a gradient to fix the system prompt to explicitly forbid that failure mode."
        
        # Use local engine for evaluator
        evaluator = tg.LLMEvaluator(eval_instruction=eval_instruction, engine=engine)
        
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
