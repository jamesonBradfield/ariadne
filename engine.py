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


# --- DEFINE OUR CONCRETE STATES ---


class SenseState(State):
    def __init__(self, language_ptr):
        super().__init__(name="SENSE")
        self.sensor = TreeSitterSensor(language_ptr)

    def tick(self, payload: JobPayload) -> Tuple[str, JobPayload]:
        # Placeholder: Logic to be implemented in Phase 2
        logger.info(f"[{self.name}] Tick with payload: {payload.intent[:50]}...")
        return "CODING", payload


class SyntaxGateState(State):
    def __init__(self, language_ptr, language_name):
        super().__init__(name="SYNTAX_GATE")
        self.syntax_gate = SyntaxGate(language_ptr)
        self.language_name = language_name

    def tick(self, payload: JobPayload) -> Tuple[str, JobPayload]:
        # Placeholder: Logic to be implemented in Phase 2
        logger.info(f"[{self.name}] Validating payload for {self.language_name}...")
        return "ACTUATE", payload


class ActuateState(State):
    def __init__(self):
        super().__init__(name="ACTUATE")

    def tick(self, payload: JobPayload) -> Tuple[str, JobPayload]:
        # Placeholder: Logic to be implemented in Phase 2
        logger.info(f"[{self.name}] Actuating...")
        return "IDLE", payload


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

    # 1. Initialize the Job Payload
    payload = JobPayload(
        intent="""
    Rewrite take_damage to implement armor mitigation and a death state:
    1. If the incoming amount is greater than 50, reduce the amount by 20% (use integer math).
    2. Subtract the final amount from self.health.
    3. If self.health drops to 0 or below, clamp it to 0 and print "CRITICAL: Player Dead!".
    4. Otherwise, print the remaining health.
    """,
        target_files=[args.file]
    )

    # 2. Detect and load profile
    profile = ProfileLoader.get_profile_for_file(args.file)
    if not profile:
        logger.critical(f"No profile found for {args.file}")
        return

    logger.info(f"Loaded {profile.name} profile.")

    # 3. Register our available states
    # NOTE: These states currently still use the old execute() internally or are broken
    # until they are refactored in the next phase.
    states_registry = {
        "SEARCH": SearchState(verbose=True),
        "SENSE": SenseState(profile.get_language_ptr()),
        "CODING": CodingState(verbose=True),
        "SYNTAX_GATE": SyntaxGateState(profile.get_language_ptr(), profile.name),
        "ACTUATE": ActuateState(),
    }

    # 4. Start the ignition
    current_state_name = "SEARCH"

    # 5. The main Engine Loop with benchmarking
    import time

    total_start_time = time.time()

    while current_state_name != "IDLE":
        active_state = states_registry.get(current_state_name)

        if not active_state:
            logger.critical(f"Unknown state requested: {current_state_name}")
            break

        # --- INTERVENTION GATE ---
        if args.step:
            print(f"\n[INTERVENE] Next State: {active_state.name}")
            user_input = input("Proceed? [Y/n]: ").strip().lower()
            if user_input == "n":
                logger.warning("Execution aborted by user.")
                break

        state_start_time = time.time()
        
        # Pure function tick: Payload in, (next_state, Payload) out.
        next_state_name, payload = active_state.tick(payload)
        
        state_end_time = time.time()
        state_duration = state_end_time - state_start_time

        logger.info(f"[BENCHMARK] {active_state.name} took {state_duration:.2f}s")
        current_state_name = next_state_name

    total_duration = time.time() - total_start_time
    logger.info(f"[BENCHMARK] Total time: {total_duration:.2f}s")
    logger.info("Engine dropped to IDLE.")


if __name__ == "__main__":
    main()
