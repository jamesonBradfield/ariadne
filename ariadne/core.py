from abc import ABC, abstractmethod
from typing import Any, Tuple


class State(ABC):
    """
    The Base Entity for the Ariadne Dataflow HFSM.
    Every state in the engine must inherit from this and implement `tick()`.
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def tick(self, payload: Any) -> Tuple[str, Any]:
        """
        The core logic loop as a pure function pipe.
        Returns: (next_state_name, mutated_payload)
        """
        pass


class EngineContext:
    """
    The orchestrator that manages the current state and transitions.
    """

    def __init__(self, initial_state: str):
        self.current_state = initial_state
        self.history = []

    def transition(self, next_state: str):
        """Log the transition and update current state."""
        self.history.append(self.current_state)
        self.current_state = next_state
