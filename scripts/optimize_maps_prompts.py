import json
import os
from typing import Any

import textgrad as tg
from textgrad.engine_experimental.litellm import LiteLLMEngine


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

    # 1. Get configuration
    default_cfg = config.get("default", {})
    local_base = default_cfg.get("api_base", "http://localhost:8080/v1")
    local_model = default_cfg.get("model", "openai/llama-cpp")

    # 2. Setup Judge (Teacher) engine - OpenRouter if available
    or_key = os.getenv("OPENROUTER_API_KEY")
    if or_key:
        print("Using OpenRouter (Qwen Plus) as the Optimization Judge...")
        # LiteLLM handles the base_url automatically for openrouter/ models
        os.environ["OPENROUTER_API_KEY"] = or_key
        judge_engine = LiteLLMEngine(model_string="openrouter/qwen/qwen3.6-plus:free")
    else:
        print(
            "No OpenRouter key found. Using local model as judge (Self-Optimization mode)."
        )
        os.environ["OPENAI_API_BASE"] = local_base
        os.environ["OPENAI_API_KEY"] = "none"
        judge_engine = LiteLLMEngine(model_string=local_model)

    # 3. Setup target (Student) engine - always local
    # We must ensure OPENAI_API_BASE is set for the local student run
    os.environ["OPENAI_API_BASE"] = local_base
    os.environ["OPENAI_API_KEY"] = "none"
    student_engine = LiteLLMEngine(model_string=local_model)

    # Set the judge engine for backward passes (gradients)
    tg.set_backward_engine(judge_engine, override=True)

    print(f"Testing prompts against Local Endpoint: {local_base} ({local_model})")

    for case in cases:
        state_name = case["state"]
        print(f"\n--- Evaluating Case: {case['id']} ({state_name}) ---")

        state_config = config["states"][state_name]

        # Define the variable to optimize
        system_prompt_var = tg.Variable(
            state_config["system_prompt"],
            role_description="The system prompt instructing the AI on how to navigate or edit the AST",
            requires_grad=True,
        )

        # Construct input
        user_prompt_template = state_config["user_prompt_template"]
        user_prompt_text = user_prompt_template
        for key, value in case.items():
            if f"{{{{{key}}}}}" in user_prompt_text:
                user_prompt_text = user_prompt_text.replace(
                    f"{{{{{key}}}}}", str(value)
                )

        if "{{error_context}}" in user_prompt_text:
            user_prompt_text = user_prompt_text.replace(
                "{{error_context}}", case.get("error_context", "")
            )

        input_var = tg.Variable(
            user_prompt_text,
            role_description="The current state of the AST and user intent",
        )

        # The Student (local model) makes the prediction
        model = tg.BlackboxLLM(engine=student_engine, system_prompt=system_prompt_var)
        prediction = model(input_var)

        print(f"Student Prediction: {prediction.value}")

        # Define evaluation criteria
        expected = case.get("expected_action") or case.get("expected_symbol_target")
        anti_expected = case.get("anti_expected_action") or case.get(
            "anti_expected_symbol_target"
        )

        eval_instruction = f"Evaluate if the prediction correctly chooses the action or target '{expected}'. It MUST NOT choose '{anti_expected}'. If it chose the wrong one, provide a gradient to fix the system prompt to explicitly forbid that failure mode."

        # The Teacher (strong model) evaluates the student
        evaluator = tg.TextLoss(
            eval_system_prompt=eval_instruction, engine=judge_engine
        )

        loss = evaluator(prediction)
        print(f"Judge Feedback: {loss.value}")

        if loss.value.lower().startswith("pass") or "correct" in loss.value.lower():
            print("Case passed. No optimization needed.")
            continue

        print("Optimizing system prompt using Judge's gradients...")

        optimizer = tg.TGD(parameters=[system_prompt_var])
        loss.backward()
        optimizer.step()

        print(f"\nOptimized System Prompt:\n{system_prompt_var.value}")

        config["states"][state_name]["system_prompt"] = system_prompt_var.value
        save_config(config)
        print(f"Updated ariadne_config.json for {state_name}")


if __name__ == "__main__":
    optimize()
