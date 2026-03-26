from abc import ABC, abstractmethod
from typing import Any, Tuple, Dict


class State(ABC):
    """Base state class for the Dataflow HFSM."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def tick(self, payload: Any) -> Tuple[str, Any]:
        """
        Pure function pipe for state logic.
        Returns: (next_state_name, mutated_payload)
        """
        pass


class StateMachine:
    """A dataflow-driven state machine runner."""

    def __init__(self):
        self.states: Dict[str, State] = {}
        self.current_state: State = None

    def add_state(self, state: State):
        """Add a state to the state machine."""
        self.states[state.name] = state

    def set_initial_state(self, state_name: str):
        """Set the initial state."""
        if state_name not in self.states:
            raise ValueError(f"State {state_name} not found")
        self.current_state = self.states[state_name]

    def run(self, initial_payload: Any) -> Any:
        """Execute the state machine until it hits 'IDLE' or None."""
        if self.current_state is None:
            raise RuntimeError("Initial state not set.")

        payload = initial_payload
        while self.current_state is not None:
            next_state_name, payload = self.current_state.tick(payload)

            if next_state_name == "IDLE" or next_state_name is None:
                break

            if next_state_name not in self.states:
                raise ValueError(f"Transition error: State '{next_state_name}' not found.")

            self.current_state = self.states[next_state_name]

        return payload
