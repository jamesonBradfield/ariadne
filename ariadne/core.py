from abc import ABC, abstractmethod
from typing import Any, Tuple, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AriadneEvent:
    """A granular event emitted by the Ariadne engine."""
    type: str # e.g. "STATE_CHANGE", "LOG", "STDOUT", "CHAT", "USER_PROMPT", "EDITOR_OPEN"
    payload: Any
    timestamp: datetime = field(default_factory=datetime.now)


class State(ABC):
    """
    The Base Entity for the Ariadne Dataflow HFSM.
    Every state in the engine must inherit from this and implement `tick()`.
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def tick(self, payload: Any, context: 'EngineContext') -> Tuple[str, Any]:
        """
        The core logic loop as a pure function pipe.
        Returns: (next_state_name, mutated_payload)
        """
        pass


class EngineContext:
    """
    The orchestrator that manages the current state and transitions.
    Holds immutable/global session dependencies.
    """

    def __init__(self, initial_state: str, intent: str, target_files: List[str], profile: Any = None):
        self.current_state = initial_state
        self.intent = intent
        self.target_files = target_files
        self.profile = profile
        self.history = []
        self.interaction_history = [] # Trace for self-optimization
        self.total_tokens = 0
        self.stop_requested = False
        self._listeners: List[Callable[[AriadneEvent], None]] = []
        
        # User response bridge
        import threading
        self._user_response_event = threading.Event()
        self._user_response_payload: Any = None

    def subscribe(self, listener: Callable[[AriadneEvent], None]):
        """Register a callback for engine events."""
        self._listeners.append(listener)

    def emit(self, event_type: str, payload: Any):
        """Broadcast an event to all subscribers."""
        event = AriadneEvent(type=event_type, payload=payload)
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass

    def transition(self, next_state: str):
        """Log the transition and update current state."""
        self.history.append(self.current_state)
        self.current_state = next_state
        self.emit("STATE_CHANGE", {"state": next_state, "history": self.history})

    def wait_for_user(self, timeout: Optional[float] = None) -> Any:
        """Blocks until a user response is received via submit_user_response."""
        self._user_response_event.clear()
        self._user_response_event.wait(timeout=timeout)
        return self._user_response_payload

    def submit_user_response(self, payload: Any):
        """Called by the UI to feed back a response to a waiting state."""
        self._user_response_payload = payload
        self._user_response_event.set()
