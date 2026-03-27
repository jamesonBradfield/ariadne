import logging
import os
from typing import Optional, Tuple, Any

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
from parent_states import TRIAGE, DISPATCH, EVALUATE, SEARCH, CODING


class ProfileLoader:
    """
    Registry and loader for language profiles based on file extension.
    """

    _profiles = [
        RustProfile(),
        # Add more profiles here
    ]

    @classmethod
    def get_profile_for_file(cls, filepath: str) -> Optional[LanguageProfile]:
        _, ext = os.path.splitext(filepath)
        for profile in cls._profiles:
            if ext in profile.extensions:
                return profile
        return None


# --- THE ENGINE RUNNER ---


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Ariadne Engine")
    parser.add_argument(
        "--step", action="store_true", help="Pause between states for manual approval"
    )
    parser.add_argument("--file", default="test.rs", help="File to operate on")
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
    profile = ProfileLoader.get_profile_for_file(args.file)
    if not profile:
        logger.critical(f"No profile found for {args.file}")
        return

    logger.info(f"Loaded {profile.name} profile.")

    # 3. Register our available states
    states_registry = {
        "TRIAGE": TRIAGE(model_info),
        "DISPATCH": DISPATCH(
            model_info, 
            test_filepath="test_contract.rs", 
            language_ptr=profile.get_language_ptr(),
            skeleton_query=profile.get_skeleton_query(),
            target_files=[args.file]
        ),
        "EVALUATE": EVALUATE(test_command="cargo test"),
        "SEARCH": SEARCH(
            model_info, 
            profile.get_language_ptr(), 
            skeleton_query=profile.get_skeleton_query(),
            node_query_template=profile.get_query("{node_name}")
        ),
        "CODING": CODING(model_info),
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
        "target_files": [args.file]
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
