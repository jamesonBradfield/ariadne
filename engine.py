import os
from typing import Optional
from profiles.base import LanguageProfile
from profiles.rust_profile import RustProfile
from components import (
    CodingState,
    DriveByWireActuator,
    ECUPromptCompiler,
    LiteLLMProvider,
    SearchState,
    SyntaxGate,
    TreeSitterSensor,
)
from core import EngineContext, State


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

    def execute(self, context: EngineContext) -> str:
        filepath = context.data["filepath"]
        target = context.data["target_func"]

        target_data = self.sensor.extract_node(
            filepath, query_string=target, capture_name="function"
        )

        if not target_data:
            print("ERROR: Could not find target node.")
            context.data["errors"].append("Node not found.")
            return "IDLE"

        print(
            f"Target acquired: bytes {target_data['start_byte']} to {target_data['end_byte']}"
        )
        context.data["extracted_node"] = target_data

        return "CODING"


class SyntaxGateState(State):
    def __init__(self, language_ptr, language_name):
        super().__init__(name="SYNTAX_GATE")
        self.syntax_gate = SyntaxGate(language_ptr)
        self.language_name = language_name

    def execute(self, context: EngineContext) -> str:
        payload = context.data.get("llm_payload", "")
        if not payload:
            print("ERROR: No payload to validate.")
            context.data["errors"].append("No payload provided.")
            return "IDLE"

        print(f"[{self.name}] Validating payload for {self.language_name}...")
        result = self.syntax_gate.validate(payload)

        if result["valid"]:
            print(f"[{self.name}] Payload is valid {self.language_name}.")
            return "ACTUATE"
        else:
            print(f"[{self.name}] Payload is invalid: {result['error_message']}")
            context.data["errors"].append(
                f"Syntax validation failed: {result['error_message']}"
            )
            return "IDLE"


class ActuateState(State):
    def __init__(self):
        super().__init__(name="ACTUATE")

    def execute(self, context: EngineContext) -> str:
        target_data = context.data["extracted_node"]
        new_payload = context.data["llm_payload"]

        if not new_payload:
            print("ERROR: No payload to actuate.")
            context.data["errors"].append("No payload for actuation.")
            return "IDLE"

        success = DriveByWireActuator.splice(
            filepath=context.data["filepath"],
            full_source=target_data["full_source"],
            start_byte=target_data["start_byte"],
            end_byte=target_data["end_byte"],
            new_payload=new_payload,
        )

        if success:
            print("Drive-by-Wire successful.")
        else:
            print("Drive-by-Wire failed.")
            context.data["errors"].append("Splice failed.")

        return "IDLE"


# --- THE ENGINE RUNNER ---


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Ariadne Engine")
    parser.add_argument("--step", action="store_true", help="Pause between states for manual approval")
    parser.add_argument("--file", default="test.rs", help="File to operate on")
    args = parser.parse_args()

    # 1. Initialize the shared memory bus
    context = EngineContext()
    context.data["filepath"] = args.file
    context.data["user_intent"] = """
    Rewrite take_damage to implement armor mitigation and a death state:
    1. If the incoming amount is greater than 50, reduce the amount by 20% (use integer math).
    2. Subtract the final amount from self.health.
    3. If self.health drops to 0 or below, clamp it to 0 and print "CRITICAL: Player Dead!".
    4. Otherwise, print the remaining health.
    """

    # 2. Detect and load profile
    profile = ProfileLoader.get_profile_for_file(context.data["filepath"])
    if not profile:
        print(f"CRITICAL: No profile found for {context.data['filepath']}")
        return

    context.data["profile"] = profile
    print(f"Loaded {profile.name} profile.")

    # 3. Register our available states
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
            print(f"CRITICAL FAULT: Unknown state requested: {current_state_name}")
            break

        active_state.enter(context)
        
        # --- INTERVENTION GATE ---
        if args.step:
            print(f"\n[INTERVENE] Next State: {active_state.name}")
            if active_state.name == "SENSE" and context.data.get("target_name"):
                print(f"Target Symbol: '{context.data['target_name']}'")
            
            user_input = input("Proceed? [Y/n/edit]: ").strip().lower()
            if user_input == 'n':
                print("Execution aborted by user.")
                break
            elif user_input == 'edit':
                if active_state.name == "SENSE":
                    new_target = input(f"Override target name (current: {context.data['target_name']}): ").strip()
                    if new_target:
                        context.data["target_name"] = new_target
                        context.data["target_func"] = profile.get_query(new_target)
                else:
                    print("Edit not supported for this state yet.")

        state_start_time = time.time()
        next_state_name = active_state.execute(context)
        state_end_time = time.time()
        state_duration = state_end_time - state_start_time
        active_state.exit(context)

        print(f"[BENCHMARK] {active_state.name} took {state_duration:.2f}s")
        current_state_name = next_state_name

    total_duration = time.time() - total_start_time
    print(f"\n[BENCHMARK] Total time: {total_duration:.2f}s")
    print("Engine dropped to IDLE.")
    if context.data["errors"]:
        print(f"Errors reported: {context.data['errors']}")


if __name__ == "__main__":
    main()
