from abc import ABC, abstractmethod
from typing import Optional
from components import TreeSitterSensor, DriveByWireActuator
import tree_sitter_rust


class State(ABC):
    """Base state class for the state machine."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def execute(self, context: dict) -> Optional[str]:
        """Execute the state's logic and return the next state name."""
        pass


class SenseState(State):
    """State responsible for sensing/extracting target data from the file."""

    def __init__(self):
        super().__init__("SENSE")
        self.sensor = None

    def execute(self, context: dict) -> Optional[str]:
        filepath = context.get("filepath")
        query_string = context.get("query_string")
        capture_name = context.get("capture_name", "function")

        if not filepath or not query_string:
            print("ERROR: Missing filepath or query_string in context")
            return None

        # Initialize sensor if not already done
        if self.sensor is None:
            self.sensor = TreeSitterSensor(tree_sitter_rust.language())

        print(f"[{self.name}] Extracting target node...")
        target_data = self.sensor.extract_node(filepath, query_string, capture_name)

        if not target_data:
            print(f"[{self.name}] Target not found. Halting.")
            return None

        print(
            f"[{self.name}] Acquired bytes {target_data['start_byte']} to {target_data['end_byte']}"
        )

        # Store target data in context for next state
        context["target_data"] = target_data
        return "ACTUATE"


class ActuateState(State):
    """State responsible for actuating/modifying the file with new payload."""

    def __init__(self):
        super().__init__("ACTUATE")
        self.actuator = DriveByWireActuator()

    def execute(self, context: dict) -> Optional[str]:
        target_data = context.get("target_data")
        new_payload = context.get("new_payload")
        filepath = context.get("filepath")

        if not target_data or not new_payload or not filepath:
            print("ERROR: Missing required context for actuation")
            return None

        print(f"[{self.name}] Splicing new payload...")
        success = self.actuator.splice(
            filepath=filepath,
            full_source=target_data["full_source"],
            start_byte=target_data["start_byte"],
            end_byte=target_data["end_byte"],
            new_payload=new_payload,
        )

        if success:
            print(f"[{self.name}] Drive-by-Wire complete. AST modified.")
            return "COMPLETE"
        else:
            print(f"[{self.name}] Drive-by-Wire failed.")
            return None


class CompleteState(State):
    """Final state indicating successful completion."""

    def __init__(self):
        super().__init__("COMPLETE")

    def execute(self, context: dict) -> Optional[str]:
        print(f"[{self.name}] Mission accomplished.")
        return None  # No further state transitions


class StateMachine:
    """Simple state machine to manage state transitions."""

    def __init__(self):
        self.states = {}
        self.current_state = None

    def add_state(self, state: State):
        """Add a state to the state machine."""
        self.states[state.name] = state

    def set_initial_state(self, state_name: str):
        """Set the initial state."""
        if state_name not in self.states:
            raise ValueError(f"State {state_name} not found")
        self.current_state = self.states[state_name]

    def execute(self, context: dict) -> bool:
        """Execute the state machine until completion or failure."""
        if self.current_state is None:
            print("ERROR: No initial state set")
            return False

        while self.current_state is not None:
            next_state_name = self.current_state.execute(context)

            if next_state_name is None:
                # Either completed successfully or failed
                if self.current_state.name == "COMPLETE":
                    print("State machine completed successfully.")
                    return True
                else:
                    print("State machine halted due to error or missing target.")
                    return False

            # Transition to next state
            if next_state_name not in self.states:
                print(f"ERROR: State {next_state_name} not found")
                return False

            self.current_state = self.states[next_state_name]
            print(f"Transitioning to {self.current_state.name}")

        return self.current_state.name == "COMPLETE" if self.current_state else False
