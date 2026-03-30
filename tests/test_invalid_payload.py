from typing import Any, Tuple
import tree_sitter_rust
from ariadne.core import EngineContext, State
from ariadne.components import TreeSitterSensor, SyntaxGate

# Mock missing legacy component
class DriveByWireActuator:
    @staticmethod
    def splice(*args, **kwargs):
        print("MOCK: DriveByWireActuator.splice called")
        return True

# --- DEFINE OUR CONCRETE STATES ---


class SenseState(State):
    def __init__(self):
        super().__init__(name="SENSE")
        self.sensor = TreeSitterSensor(tree_sitter_rust.language())

    def tick(self, payload: Any) -> Tuple[str, Any]:
        return "IDLE", payload

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

        return "SYNTAX_GATE"  # Shift to syntax gate


class SyntaxGateState(State):
    def __init__(self):
        super().__init__(name="SYNTAX_GATE")
        self.syntax_gate = SyntaxGate(tree_sitter_rust.language())

    def tick(self, payload: Any) -> Tuple[str, Any]:
        return "IDLE", payload

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

    def tick(self, payload: Any) -> Tuple[str, Any]:
        return "IDLE", payload

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
    context.data["target_func"] = """
    (function_item
        name: (identifier) @func_name
        (#eq? @func_name "take_damage")
    ) @function
    """
    # Intentionally invalid Rust payload - missing semicolon
    context.data["llm_payload"] = """    fn take_damage(&mut self, amount: i32) {
        println!("The ECS State Machine is fully operational. Took {} damage", amount)
    }
"""

    # 2. Register our available states
    states_registry = {
        "SENSE": SenseState(),
        "SYNTAX_GATE": SyntaxGateState(),
        "ACTUATE": ActuateState(),
    }

    # 3. Start the ignition
    current_state_name = "SENSE"

    # 4. The main Engine Loop
    while current_state_name != "IDLE":
        # Look up the state object
        active_state = states_registry.get(current_state_name)

        if not active_state:
            print(f"CRITICAL FAULT: Unknown state requested: {current_state_name}")
            break

        active_state.enter(context)
        # Execute returns the string name of the next state
        next_state_name = active_state.execute(context)
        active_state.exit(context)

        # Shift gears
        current_state_name = next_state_name

    print("\nEngine dropped to IDLE. Execution finished.")
    if context.data["errors"]:
        print(f"Errors reported: {context.data['errors']}")


if __name__ == "__main__":
    main()
