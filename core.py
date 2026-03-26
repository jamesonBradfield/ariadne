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
