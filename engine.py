import argparse
import logging
import os
import json
from typing import Any, Dict, List, Optional, Tuple

from core import EngineContext, State
from payloads import JobPayload
from primitives import QueryLLM, ASTSplice
from parent_states import TRIAGE, DISPATCH, EVALUATE, SEARCH
from components import TreeSitterSensor, SyntaxGate

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
            from profiles.rust_profile import RustProfile
            return RustProfile()
        elif name.lower() == "python":
            from profiles.python_profile import PythonProfile
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


class SenseState(State):
    """
    Acquires the exact AST coordinates for target symbols.
    """
    def __init__(self, profile):
        super().__init__("SENSE")
        self.profile = profile
        self.sensor = TreeSitterSensor(profile.get_language_ptr())

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        if job.current_file_index >= len(job.target_files):
            return "SUCCESS", job

        filepath = job.target_files[job.current_file_index]
        job.extracted_nodes = []

        # Use symbols from job.target_symbols (populated by SEARCH)
        if not job.target_symbols:
            logger.error(f"[{self.name}] No target symbols provided. Aborting.")
            return "ABORT", job

        for symbol in job.target_symbols:
            query = self.profile.get_query(symbol)
            node_data = self.sensor.extract_node(filepath, query, self.profile.target_capture_name)

            if node_data:
                node_data["symbol"] = symbol
                job.extracted_nodes.append(node_data)
                logger.info(f"[{self.name}] Target acquired in {filepath}: {symbol}")
            else:
                logger.warning(f"[{self.name}] Symbol not found in {filepath}: {symbol}")

        if not job.extracted_nodes:
            job.current_file_index += 1
            return "SENSE", job

        return "CODING", job


class CodingState(State):
    """
    Uses LLM to rewrite the acquired AST nodes via strict JSON schema.
    """
    def __init__(self, config_manager: ConfigManager, profile: Any):
        super().__init__("CODING")
        self.config_manager = config_manager
        self.config = config_manager.get_model_info("CODING")
        self.llm = QueryLLM(model=self.config.get("model"), api_base=self.config.get("api_base"))
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        if not job.extracted_nodes:
            return "SENSE", job

        logger.info(f"[{self.name}] --- AMNESIC TICK: Fresh LLM Context for {job.target_files[job.current_file_index]} ---")

        error_context = ""
        if job.llm_feedback:
            error_context += f"PREVIOUS ERROR: {job.llm_feedback}\n\n"
        if hasattr(job, "test_stdout") and job.test_stdout:
            error_context += f"TEST FAILURE (Fix this error in your rewrite):\n{job.test_stdout}\n\n"

        context_str = ""
        for node in job.extracted_nodes:
            context_str += f"--- Symbol: {node['symbol']} ---\n{node['node_string']}\n\n"

        variables = {
            "language": self.profile.name,
            "intent": job.intent,
            "error_context": error_context,
            "context_str": context_str,
            "coding_example": self.profile.coding_example
        }

        system_prompt = self.config_manager.render_prompt(
            self.config.get("system_prompt", ""), variables
        )
        user_prompt = self.config_manager.render_prompt(
            self.config.get("user_prompt_template", ""), variables
        )

        status, response = self.llm.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": self.config.get("params", {}),
            "post_process": self.config.get("post_process")
        })

        if status != "SUCCESS":
            logger.error(f"[{self.name}] LLM generation failed: {response}")
            return "ABORT", job

        job.fixed_code = response  # Now a dictionary with 'edits'
        return "SYNTAX_GATE", job


class SyntaxGateState(State):
    """
    Validates all generated code snippets before they touch the disk.
    """
    def __init__(self, profile):
        super().__init__("SYNTAX_GATE")
        self.gate = SyntaxGate(profile.get_language_ptr())

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        logger.info(f"[{self.name}] Validating surgical ASTs...")

        if not isinstance(job.fixed_code, dict) or "edits" not in job.fixed_code:
            job.llm_feedback = "Response must be a JSON object with an 'edits' array."
            return "CODING", job

        for edit in job.fixed_code["edits"]:
            result = self.gate.validate(edit["new_code"])
            if not result["valid"]:
                error_msg = result['error_message']
                symbol_name = edit.get('symbol', 'unknown')
                logger.error(f"[{self.name}] Syntax validation failed for {symbol_name}: {error_msg}")
                job.llm_feedback = f"Syntax error in {symbol_name}: {error_msg}"
                return "CODING", job

        job.llm_feedback = ""
        return "ACTUATE", job


class ActuateState(State):
    """
    Splices all valid edits into the file in reverse byte-order.
    """
    def __init__(self):
        super().__init__("ACTUATE")
        self.splicer = ASTSplice()

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        if not job.extracted_nodes:
            logger.error(f"[{self.name}] No surgical target acquired! Aborting splice.")
            return "ABORT", job

        filepath = job.target_files[job.current_file_index]

        edits_to_apply = []
        for edit in job.fixed_code.get("edits", []):
            symbol = edit.get("symbol")
            new_code = edit.get("new_code")
            # Find the corresponding node data extracted in SENSE
            node_data = next((n for n in job.extracted_nodes if n["symbol"] == symbol), None)
            if node_data:
                edits_to_apply.append({
                    "start_byte": node_data["start_byte"],
                    "end_byte": node_data["end_byte"],
                    "new_code": new_code
                })

        if not edits_to_apply:
            logger.error(f"[{self.name}] No matching symbols found in edits!")
            job.llm_feedback = "Ensure 'symbol' matches the extracted node names."
            return "CODING", job

        logger.info(f"[{self.name}] Splicing {len(edits_to_apply)} nodes in {filepath}")

        status, result = self.splicer.tick({
            "filepath": filepath,
            "edits": edits_to_apply
        })

        if status == "SUCCESS":
            return "EVALUATE", job
        
        logger.error(f"[{self.name}] Splice failed: {result}")
        return "ABORT", job


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
            test_command=f"python run_rust_tests.py {target_files[0]} test_contract{profile.extensions[0]}" 
            if profile.name == "Rust" else " ".join(profile.check_command)
        ),
        "SEARCH": SEARCH(config_manager, profile),
        "SENSE": SenseState(profile),
        "CODING": CodingState(config_manager, profile),
        "SYNTAX_GATE": SyntaxGateState(profile),
        "ACTUATE": ActuateState(),
    }

    # 4. Initialize Engine Context
    context = EngineContext(initial_state=args.initial_state.upper())
    
    if context.current_state == "TRIAGE":
        payload = {"input": args.intent, "target_files": target_files}
    else:
        # If bypassing TRIAGE/DISPATCH, mock the payload structure they would have created
        payload = JobPayload(intent=args.intent, target_files=target_files)

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
