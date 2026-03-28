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
    Acquires the exact AST coordinates for a target symbol.
    """
    def __init__(self, profile):
        super().__init__("SENSE")
        self.profile = profile
        self.sensor = TreeSitterSensor(profile.get_language_ptr())

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        if job.current_file_index >= len(job.target_files):
            return "SUCCESS", job

        filepath = job.target_files[job.current_file_index]
        # In a real system, SEARCH would pass the exact symbol name.
        # For the multi-file refactor, we use the intent-based symbol.
        symbol = "take_damage" 

        query = self.profile.get_query(symbol)
        node_data = self.sensor.extract_node(filepath, query, "function")

        if node_data:
            job.extracted_node = node_data
            logger.info(f"[{self.name}] Target acquired in {filepath}")
            return "CODING", job

        logger.warning(f"[{self.name}] Symbol not found in {filepath}, skipping.")
        job.current_file_index += 1
        return "SENSE", job


class CodingState(State):
    """
    Uses LLM to rewrite the acquired AST node.
    """
    def __init__(self, model_info: Dict[str, Any], profile: Any):
        super().__init__("CODING")
        self.llm = LiteLLMProvider(
            model=model_info.get("model"), 
            base_url=model_info.get("api_base"),
            verbose=True
        )
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        node_data = job.extracted_node
        if not node_data:
            return "SENSE", job

        logger.info(f"[{self.name}] --- AMNESIC TICK: Fresh LLM Context for {job.target_files[job.current_file_index]} ---")
        
        system_prompt = (
            f"You are an expert {self.profile.name} developer. You act as an execution engine. "
            f"You only output raw, valid {self.profile.name} code. NO markdown formatting. "
            f"NO backticks. NO conversational text or explanations."
        )
        
        user_prompt = f"Rewrite this code to fulfill the following intent: {job.intent}\n\n"
        if job.llm_feedback:
            user_prompt += f"PREVIOUS SYNTAX ERROR: {job.llm_feedback}\n\n"
            
        if hasattr(job, "test_stdout") and job.test_stdout:
            user_prompt += f"TEST FAILURE (Fix this error in your rewrite):\n{job.test_stdout}\n\n"
            
        user_prompt += f"Code to rewrite:\n{node_data['node_string']}"

        fixed_code = self.llm.generate(system_prompt, user_prompt)
        if fixed_code is None:
            logger.error(f"[{self.name}] LLM generation failed (returned None).")
            return "ABORT", job
            
        job.fixed_code = fixed_code
        return "SYNTAX_GATE", job


class SyntaxGateState(State):
    """
    Validates the generated code before it touches the disk.
    """
    def __init__(self, profile):
        super().__init__("SYNTAX_GATE")
        self.gate = SyntaxGate(profile.get_language_ptr())

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        logger.info(f"[{self.name}] Validating surgical AST...")
        result = self.gate.validate(job.fixed_code)
        
        if result["valid"]:
            return "ACTUATE", job
        
        logger.error(f"[{self.name}] Syntax validation failed: {result['error_message']}")
        job.llm_feedback = f"Syntax error or illegal markdown: {result['error_message']}"
        return "CODING", job


class ActuateState(State):
    def __init__(self):
        super().__init__("ACTUATE")
        self.splicer = ASTSplice()

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        node_data = getattr(job, "extracted_node", None)
        if not node_data or "full_source" not in node_data:
            logger.error(f"[{self.name}] No surgical target acquired! Aborting splice.")
            return "ABORT", job

        filepath = job.target_files[job.current_file_index]
        
        logger.info(f"[{self.name}] Splicing {filepath} via Drive-by-Wire")
        
        status, result = self.splicer.tick({
            "filepath": filepath,
            "full_source": node_data["full_source"],
            "start_byte": node_data["start_byte"],
            "end_byte": node_data["end_byte"],
            "new_code": job.fixed_code
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
    payload = {"input": "Implement armor mitigation and death state in take_damage method."}

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
