import argparse
import logging
import os
import json
from typing import Any, Dict, List, Optional, Tuple

from ariadne.core import EngineContext, State
from ariadne.payloads import JobPayload
from ariadne.primitives import QueryLLM, ASTSplice
from ariadne.states import TRIAGE, DISPATCH, EVALUATE, THINKING, SEARCH, SENSE, CODING, SYNTAX_GATE, ACTUATE
from ariadne.components import TreeSitterSensor, SyntaxGate

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ariadne.core")


class ConfigManager:
    """
    Manages state-specific LLM configurations from a JSON file.
    """
    def __init__(self, config_path: str = "ariadne_config.json"):
        self.config = {
            "default": {
                "model": "openai/llama-cpp",
                "api_base": "http://localhost:8080/v1",
                "api_key": "none",
                "params": {
                    "temperature": 0.0,
                    "max_tokens": 4096
                }
            },
            "states": {}
        }
        
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    user_config = json.load(f)
                    # Deep merge defaults
                    if "default" in user_config:
                        for k, v in user_config["default"].items():
                            if k == "params" and isinstance(v, dict):
                                self.config["default"]["params"].update(v)
                            else:
                                self.config["default"][k] = v
                    if "states" in user_config:
                        self.config["states"].update(user_config["states"])
                logger.info(f"Loaded LLM configuration from {config_path}")
            except Exception as e:
                logger.error(f"Failed to load config {config_path}: {e}. Using defaults.")

    def get_model_info(self, state_name: str) -> Dict[str, Any]:
        """
        Returns the merged model configuration for a specific state.
        """
        # Start with default
        info = json.loads(json.dumps(self.config["default"])) # Deep copy
        
        state_config = self.config["states"].get(state_name, {})
        
        # Merge state-specific config
        for k, v in state_config.items():
            if k == "params" and isinstance(v, dict):
                info["params"].update(v)
            else:
                info[k] = v
        return info

    @staticmethod
    def render_prompt(template: str, variables: Dict[str, Any]) -> str:
        """
        Simple {{variable}} substitution.
        """
        result = template
        for k, v in variables.items():
            result = result.replace(f"{{{{{k}}}}}", str(v))
        return result


class ProfileLoader:
    """
    Handles loading language profiles and expanding target lists.
    """
    @staticmethod
    def load_profile(name: str):
        if name.lower() == "rust":
            from ariadne.profiles.rust_profile import RustProfile
            return RustProfile()
        elif name.lower() == "python":
            from ariadne.profiles.python_profile import PythonProfile
            return PythonProfile()
        else:
            raise ValueError(f"Unsupported profile: {name}")

    @staticmethod
    def expand_targets(targets: List[str], profile) -> List[str]:
        expanded = []
        ignore_handler = IgnoreHandler()
        for t in targets:
            if os.path.isfile(t):
                expanded.append(t)
            elif os.path.isdir(t):
                for root, dirs, files in os.walk(t):
                    # Prune ignored directories in-place
                    dirs[:] = [d for d in dirs if not ignore_handler.is_ignored(os.path.join(root, d))]
                    
                    for f in files:
                        full_path = os.path.join(root, f)
                        if any(full_path.endswith(ext) for ext in profile.extensions):
                            if not ignore_handler.is_ignored(full_path):
                                expanded.append(full_path)
        return expanded


class IgnoreHandler:
    """
    Handles .ariadneignore and .gitignore logic.
    """
    def __init__(self):
        self.ignore_patterns = [".venv", "target", ".git", "__pycache__", ".ruff_cache"]
        if os.path.exists(".ariadneignore"):
            with open(".ariadneignore", "r") as f:
                self.ignore_patterns.extend([line.strip() for line in f if line.strip() and not line.startswith("#")])

    def is_ignored(self, path: str) -> bool:
        return any(pattern in path for pattern in self.ignore_patterns)


def main():
    parser = argparse.ArgumentParser(description="Ariadne ECU: Surgical Code Repair Engine")
    parser.add_argument("--targets", nargs="+", help="Files or directories to ingest")
    parser.add_argument("--profile", default="rust", help="Language profile to use")
    parser.add_argument("--config", default="ariadne_config.json", help="Path to LLM configuration JSON")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--intent", default="Implement armor mitigation and death state in take_damage method.", help="The user request or coding intent")
    parser.add_argument("--initial-state", default="TRIAGE", help="The starting state for the engine")
    args = parser.parse_args()

    logging.getLogger("ariadne").setLevel(args.log_level)

    # 1. Load Configuration and Profile
    config_manager = ConfigManager(args.config)
    profile = ProfileLoader.load_profile(args.profile)
    
    # 2. Expand Targets
    target_files = ProfileLoader.expand_targets(args.targets or ["."], profile)
    if not target_files:
        logger.critical("No target files found! Check your --targets or .ariadneignore.")
        return

    logger.info(f"Loaded {profile.name} profile with {len(target_files)} files.")

    # 3. Register our available states
    states_registry = {
        "TRIAGE": TRIAGE(config_manager),
        "DISPATCH": DISPATCH(
            config_manager, 
            test_filepath=f"test_contract{profile.extensions[0]}", 
            profile=profile,
            target_files=target_files
        ),
        "EVALUATE": EVALUATE(
            test_command=f"python scripts/run_rust_tests.py {target_files[0]} test_contract{profile.extensions[0]}" 
            if profile.name == "Rust" else " ".join(profile.check_command)
        ),
        "THINKING": THINKING(config_manager, profile),
        "SEARCH": SEARCH(config_manager, profile),

        "SENSE": SENSE(profile),
        "CODING": CODING(config_manager, profile),
        "SYNTAX_GATE": SYNTAX_GATE(profile),
        "ACTUATE": ACTUATE(),
    }

    # 4. Initialize Engine Context
    # PERCEPTION FIRST: Start with EVALUATE to see the current state
    context = EngineContext(initial_state="EVALUATE")
    
    # Payload starts with raw input for TRIAGE to distill later
    payload = JobPayload(input=args.intent, target_files=target_files)

    # 5. Run the Loop
    while context.current_state != "SUCCESS" and context.current_state != "ABORT":
        logger.info(f"--- TICKING: {context.current_state} ---")
        active_state = states_registry.get(context.current_state)
        
        if not active_state:
            logger.error(f"State {context.current_state} not found!")
            break

        import time
        start_time = time.time()
        
        current_state_name, payload = active_state.tick(payload)
        
        elapsed = time.time() - start_time
        logger.info(f"[BENCHMARK] {context.current_state} took {elapsed:.2f}s")
        
        context.transition(current_state_name)

    logger.info(f"Engine dropped to terminal state: {context.current_state}")


if __name__ == "__main__":
    main()
