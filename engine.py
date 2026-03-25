from components import (
    CodingState,
    DriveByWireActuator,
    ECUPromptCompiler,
    LLMProvider,
    SearchState,
    SyntaxGate,
    TreeSitterSensor,
)
from core import EngineContext, State

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
            return "IDLE"  # Abort

        print(
            f"Target acquired: bytes {target_data['start_byte']} to {target_data['end_byte']}"
        )
        context.data["extracted_node"] = target_data

        return "CODING"  # Shift to coding state


class SyntaxGateState(State):
    def __init__(self, language_ptr):
        super().__init__(name="SYNTAX_GATE")
        self.syntax_gate = SyntaxGate(language_ptr)

    def execute(self, context: EngineContext) -> str:
        # Get the payload to validate (this would come from LLM in later phases)
        payload = context.data.get("llm_payload", "")
        if not payload:
            print("ERROR: No payload to validate.")
            context.data["errors"].append("No payload provided.")
            return "IDLE"

        print(f"[{self.name}] Validating payload...")
        result = self.syntax_gate.validate(payload)

        if result["valid"]:
            print(f"[{self.name}] Payload is valid Rust.")
            # Keep the payload as is for actuation
            return "ACTUATE"
        else:
            print(f"[{self.name}] Payload is invalid: {result['error_message']}")
            context.data["errors"].append(
                f"Syntax validation failed: {result['error_message']}"
            )
            # Optionally, we could try to fix it here, but for now we abort
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

        return "IDLE"  # Mission complete, drop to idle


# --- THE ENGINE RUNNER ---


def main():
    # 1. Initialize the shared memory bus
    context = EngineContext()
    context.data["filepath"] = "test.rs"
    # Placeholder for target_func; will be set by SEARCH state if needed.
    context.data["target_func"] = ""
    # Give the LLM its marching orders
    context.data["user_intent"] = """
    Rewrite take_damage to implement armor mitigation and a death state:
    1. If the incoming amount is greater than 50, reduce the amount by 20% (use integer math).
    2. Subtract the final amount from self.health.
    3. If self.health drops to 0 or below, clamp it to 0 and print "CRITICAL: Player Dead!".
    4. Otherwise, print the remaining health.
    """
    # Set language for profile-specific components
    context.data["language"] = "Rust"

    # 2. Register our available states
    # Import tree_sitter_rust here for language-specific instantiation
    import tree_sitter_rust

    states_registry = {
        "SEARCH": SearchState(verbose=True),
        "SENSE": SenseState(tree_sitter_rust.language()),
        "CODING": CodingState(),
        "SYNTAX_GATE": SyntaxGateState(tree_sitter_rust.language()),
        "ACTUATE": ActuateState(),
    }

    # 3. Start the ignition
    current_state_name = "SEARCH"

    # 4. The main Engine Loop with benchmarking
    import time

    total_start_time = time.time()

    while current_state_name != "IDLE":
        # Look up the state object
        active_state = states_registry.get(current_state_name)

        if not active_state:
            print(f"CRITICAL FAULT: Unknown state requested: {current_state_name}")
            break

        active_state.enter(context)
        state_start_time = time.time()
        # Execute returns the string name of the next state
        next_state_name = active_state.execute(context)
        state_end_time = time.time()
        state_duration = state_end_time - state_start_time
        active_state.exit(context)

        print(
            f"[BENCHMARK] {active_state.name} state took {state_duration:.2f} seconds"
        )

        # Shift gears
        current_state_name = next_state_name

    total_end_time = time.time()
    total_duration = total_end_time - total_start_time
    print(f"[BENCHMARK] Total engine execution time: {total_duration:.2f} seconds")
    print("\nEngine dropped to IDLE. Execution finished.")
    if context.data["errors"]:
        print(f"Errors reported: {context.data['errors']}")


if __name__ == "__main__":
    main()
