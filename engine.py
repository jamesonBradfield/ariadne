import argparse
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from core import EngineContext, State
from payloads import JobPayload
from primitives import ExtractAST, QueryLLM, ExecuteCommand, PromptUser, WriteFile, ASTSplice
from parent_states import TRIAGE, DISPATCH, EVALUATE, SEARCH
from components import LiteLLMProvider, TreeSitterSensor, SyntaxGate

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ariadne.core")


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

        # If no symbols provided (e.g. bypassed SEARCH), fallback to intent heuristic
        symbols_to_find = job.target_symbols if job.target_symbols else ["take_damage"]

        for symbol in symbols_to_find:
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
    def __init__(self, model_info: Dict[str, Any], profile: Any):
        super().__init__("CODING")
        # Switch to QueryLLM to utilize the built-in JSON schema parsing
        self.llm = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        if not job.extracted_nodes:
            return "SENSE", job

        logger.info(f"[{self.name}] --- AMNESIC TICK: Fresh LLM Context for {job.target_files[job.current_file_index]} ---")

        system_prompt = self.profile.coding_system_prompt

        user_prompt = f"Rewrite this code to fulfill the following intent: {job.intent}\n\n"

        if job.llm_feedback:
            user_prompt += f"PREVIOUS ERROR: {job.llm_feedback}\n\n"

        if hasattr(job, "test_stdout") and job.test_stdout:
            user_prompt += f"TEST FAILURE (Fix this error in your rewrite):\n{job.test_stdout}\n\n"

        context_str = ""
        for node in job.extracted_nodes:
            context_str += f"--- Symbol: {node['symbol']} ---\n{node['node_string']}\n\n"

        user_prompt += f"Code to rewrite:\n{context_str}"

        schema = {
            "edits": [
                {
                    "symbol": "string (the name of the function/struct being edited)",
                    "new_code": "string (the complete rewritten code for this symbol)"
                }
            ]
        }

        status, response = self.llm.tick({
            "system": system_prompt,
            "user": user_prompt,
            "schema": schema
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
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()

    logging.getLogger("ariadne").setLevel(args.log_level)

    # 1. Load Profile
    profile = ProfileLoader.load_profile(args.profile)
    
    # 2. Expand Targets
    target_files = ProfileLoader.expand_targets(args.targets or ["."], profile)
    logger.info(f"Loaded {profile.name} profile with {len(target_files)} files.")

    model_info = {
        "model": os.getenv("ARIADNE_MODEL"),
        "api_base": os.getenv("ARIADNE_API_BASE"),
    }

    # 3. Register our available states
    states_registry = {
        "TRIAGE": TRIAGE(model_info),
        "DISPATCH": DISPATCH(
            model_info, 
            test_filepath=f"test_contract{profile.extensions[0]}", 
            profile=profile,
            target_files=target_files
        ),
        "EVALUATE": EVALUATE(
            test_command=f"python run_rust_tests.py {target_files[0]} test_contract{profile.extensions[0]}" 
            if profile.name == "Rust" else " ".join(profile.check_command)
        ),
        "SEARCH": SEARCH(
            model_info, 
            profile=profile, 
            node_query_template=profile.get_query("{node_name}")
        ),
        "SENSE": SenseState(profile),
        "CODING": CodingState(model_info, profile),
        "SYNTAX_GATE": SyntaxGateState(profile),
        "ACTUATE": ActuateState(),
    }

    # 4. Initialize Engine Context
    context = EngineContext(initial_state="TRIAGE")
    payload = {"input": "Add a `stamina: f32` field to the Entity struct (default 100.0) and modify the `take_damage` function to subtract 10.0 stamina per hit."}

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
