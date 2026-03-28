import logging
import os
from typing import Optional, Tuple, Any, List

from components import (
    CodingState,
    DriveByWireActuator,
    ECUPromptCompiler,
    LiteLLMProvider,
    SearchState,
    SyntaxGate,
    TreeSitterSensor,
)

# This creates a logger named 'core' that other files can import
logger = logging.getLogger("ariadne.core")
from core import State
from payloads import JobPayload, ContextPayload
from profiles.base import LanguageProfile
from profiles.rust_profile import RustProfile
from profiles.python_profile import PythonProfile
from parent_states import TRIAGE, DISPATCH, EVALUATE, SEARCH


class IgnoreHandler:
    """Handles .ariadneignore patterns."""
    def __init__(self, ignore_file=".ariadneignore"):
        self.patterns = []
        if os.path.exists(ignore_file):
            with open(ignore_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self.patterns.append(line)

    def is_ignored(self, path: str) -> bool:
        import fnmatch
        norm_path = os.path.normpath(path).replace(os.sep, "/")
        for pattern in self.patterns:
            # Directory ignore (e.g., .venv/)
            if pattern.endswith("/") and (pattern.strip("/") + "/") in norm_path:
                return True
            # File/glob ignore (e.g., *.pyc)
            if fnmatch.fnmatch(os.path.basename(path), pattern) or fnmatch.fnmatch(norm_path, pattern):
                return True
        return False


class ProfileLoader:
    """
    Registry and loader for language profiles based on file extension.
    """

    _profiles = [
        RustProfile(),
        PythonProfile(),
    ]

    @classmethod
    def get_profile_for_file(cls, filepath: str) -> Optional[LanguageProfile]:
        _, ext = os.path.splitext(filepath)
        for profile in cls._profiles:
            if ext in profile.extensions:
                return profile
        return None

    @classmethod
    def expand_targets(cls, targets: List[str]) -> Tuple[Optional[LanguageProfile], List[str]]:
        """
        Takes a list of files or directories, detects the primary profile, 
        and expands all targets into a list of matching files.
        """
        ignore_handler = IgnoreHandler()
        
        # Pass 1: Find the primary profile from the targets
        primary_profile = None
        for target in targets:
            if ignore_handler.is_ignored(target):
                continue

            if os.path.isfile(target):
                primary_profile = cls.get_profile_for_file(target)
            elif os.path.isdir(target):
                for root, dirs, files in os.walk(target):
                    # Prune ignored directories in-place for efficiency
                    dirs[:] = [d for d in dirs if not ignore_handler.is_ignored(os.path.join(root, d))]
                    for f in files:
                        path = os.path.join(root, f)
                        if ignore_handler.is_ignored(path):
                            continue
                        primary_profile = cls.get_profile_for_file(path)
                        if primary_profile: break
                    if primary_profile: break
            if primary_profile: break

        if not primary_profile:
            return None, []

        # Pass 2: Expand all files matching that profile's extensions
        all_files = []
        valid_extensions = primary_profile.extensions
        
        for target in targets:
            if ignore_handler.is_ignored(target):
                continue

            if os.path.isfile(target):
                if os.path.splitext(target)[1] in valid_extensions:
                    all_files.append(target)
            elif os.path.isdir(target):
                for root, dirs, files in os.walk(target):
                    # Prune ignored directories
                    dirs[:] = [d for d in dirs if not ignore_handler.is_ignored(os.path.join(root, d))]
                    for f in files:
                        path = os.path.join(root, f)
                        if ignore_handler.is_ignored(path):
                            continue
                        if os.path.splitext(path)[1] in valid_extensions:
                            all_files.append(path)

        return primary_profile, list(set(all_files))


# --- SURGICAL STATES ---


class SenseState(State):
    def __init__(self, profile: LanguageProfile):
        super().__init__("SENSE")
        self.profile = profile
        self.sensor = TreeSitterSensor(profile.get_language_ptr())

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        if not hasattr(job, "current_file_index"):
            job.current_file_index = 0

        # Reset node state for this file attempt to prevent bleeding
        job.extracted_node = None

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
    def __init__(self, model_info: dict, profile: LanguageProfile):
        super().__init__("CODING")
        self.profile = profile
        self.llm = LiteLLMProvider(model=model_info["model"], base_url=model_info["api_base"])

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        node_data = getattr(job, "extracted_node", {})
        logger.info(f"[{self.name}] --- AMNESIC TICK: Fresh LLM Context for {job.target_files[job.current_file_index]} ---")
        
        system, user = ECUPromptCompiler.compile(
            self.profile.name, 
            node_data.get("node_string", ""), 
            job.intent
        )

        # Append feedback if this is a retry
        if job.llm_feedback:
            user += f"\n\nPREVIOUS ERROR: {job.llm_feedback}\nPlease fix this and return ONLY the raw code."
        
        raw_payload = self.llm.generate(system, user)
        
        # Surgical cleaning of markdown blocks using regex
        import re
        code_block_match = re.search(r"```(?:\w+)?\n(.*?)\n```", raw_payload, re.DOTALL)
        if code_block_match:
            clean_payload = code_block_match.group(1).strip()
        else:
            clean_payload = raw_payload.strip().replace("```", "")
        
        job.llm_payload = clean_payload
        return "SYNTAX_GATE", job


class SyntaxGateState(State):
    def __init__(self, profile: LanguageProfile):
        super().__init__("SYNTAX_GATE")
        self.gate = SyntaxGate(profile.get_language_ptr())

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        logger.info(f"[{self.name}] Validating surgical AST...")
        result = self.gate.validate(job.llm_payload)
        if result["valid"]:
            job.llm_feedback = "" # Clear feedback on success
            return "ACTUATE", job
        
        logger.error(f"[{self.name}] Syntax validation failed: {result['error_message']}")
        job.llm_feedback = f"Syntax error or illegal markdown: {result['error_message']}"
        return "CODING", job


class ActuateState(State):
    def __init__(self):
        super().__init__("ACTUATE")

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        node_data = getattr(job, "extracted_node", None)
        if not node_data or "full_source" not in node_data:
            logger.error(f"[{self.name}] No surgical target acquired! Aborting splice.")
            return "ABORT", job

        filepath = job.target_files[job.current_file_index]
        
        logger.info(f"[{self.name}] Splicing {filepath} via Drive-by-Wire")
        success = DriveByWireActuator.splice(
            filepath,
            node_data["full_source"],
            node_data["start_byte"],
            node_data["end_byte"],
            job.llm_payload
        )
        
        if success:
            job.current_file_index += 1
            if job.current_file_index < len(job.target_files):
                return "SENSE", job
            return "EVALUATE", job
        
        return "ABORT", job


class SearchState(SEARCH):
    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        # Perform the base search logic
        _, job = super().tick(job)
        # Redirect the pipeline to our granular states
        return "SENSE", job


# --- THE ENGINE RUNNER ---


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Ariadne Engine")
    parser.add_argument(
        "--step", action="store_true", help="Pause between states for manual approval"
    )
    parser.add_argument(
        "--targets", 
        nargs="+", 
        default=["test.rs"], 
        help="Files or directories to operate on"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set the logging level",
    )
    args = parser.parse_args()

    # Configure logging based on flag
    numeric_level = getattr(logging, args.log_level.upper(), None)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Silence noisy third-party loggers
    logging.getLogger("litellm").setLevel(logging.WARNING)
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    # 1. Configuration and Model Setup
    model_info = {
        "model": os.getenv("ARIADNE_MODEL") or "openai/llama-cpp",
        "api_base": os.getenv("ARIADNE_API_BASE") or "http://localhost:8080/v1"
    }

    # 2. Detect and load profile
    profile, target_files = ProfileLoader.expand_targets(args.targets)
    if not profile:
        logger.critical(f"No profile found for targets: {args.targets}")
        return

    logger.info(f"Loaded {profile.name} profile with {len(target_files)} files.")

    # 3. Register our available states
    states_registry = {
        "TRIAGE": TRIAGE(model_info),
        "DISPATCH": DISPATCH(
            model_info, 
            test_filepath=f"test_contract{profile.extensions[0]}", 
            profile=profile,
            target_files=target_files
        ),
        "EVALUATE": EVALUATE(test_command=" ".join(profile.check_command)),
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

    # 4. Start the ignition
    current_state_name = "TRIAGE"
    
    # We start with a dict payload to preserve target_files through TRIAGE
    payload = {
        "input": """
        Rewrite take_damage to implement armor mitigation and a death state:
        1. If the incoming amount is greater than 50, reduce the amount by 20% (use integer math).
        2. Subtract the final amount from self.health.
        3. If self.health drops to 0 or below, clamp it to 0 and print "CRITICAL: Player Dead!".
        4. Otherwise, print the remaining health.
        """,
        "target_files": target_files
    }

    # 5. The main Engine Loop with benchmarking
    import time

    total_start_time = time.time()

    # Terminal states for the loop
    terminal_states = ["IDLE", "SUCCESS", "HALT", "ABORT", None]

    while current_state_name not in terminal_states:
        active_state = states_registry.get(current_state_name)

        if not active_state:
            logger.critical(f"Unknown state requested: {current_state_name}")
            break

        # --- INTERVENTION GATE ---
        if args.step:
            print(f"\n[INTERVENE] Next State: {active_state.name}")
            ui = input("Proceed? [Y/n]: ").strip().lower()
            if ui == "n":
                logger.warning("Execution aborted by user.")
                break

        state_start_time = time.time()
        
        # Pure function tick: Payload in, (next_state, Payload) out.
        logger.info(f"--- TICKING: {active_state.name} ---")
        current_state_name, payload = active_state.tick(payload)
        
        state_end_time = time.time()
        state_duration = state_end_time - state_start_time

        logger.info(f"[BENCHMARK] {active_state.name} took {state_duration:.2f}s")

    total_duration = time.time() - total_start_time
    logger.info(f"[BENCHMARK] Total time: {total_duration:.2f}s")
    logger.info(f"Engine dropped to terminal state: {current_state_name}")


if __name__ == "__main__":
    main()
