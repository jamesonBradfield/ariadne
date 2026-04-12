from abc import ABC, abstractmethod
from typing import Any, Tuple, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AriadneEvent:
    type: str
    payload: Any
    timestamp: datetime = field(default_factory=datetime.now)


class State(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def tick(self, payload: Any, context: "EngineContext") -> Tuple[str, Any]:
        pass


class Services:
    def __init__(self):
        self.lsp = None
        self.analysis = None

    def start(self) -> None:
        if self.lsp:
            self.lsp.start()
        if self.analysis:
            self.analysis.start()

    def stop(self) -> None:
        if self.analysis:
            self.analysis.stop()
        if self.lsp:
            self.lsp.stop()


class EngineContext:
    def __init__(
        self,
        initial_state: str,
        intent: str,
        target_files: List[str],
        profile: Any = None,
    ):
        self.current_state = initial_state
        self.intent = intent
        self.target_files = target_files
        self.profile = profile
        self.history = []
        self.interaction_history = []
        self.total_tokens = 0
        self.stop_requested = False
        self._listeners: List[Callable[[AriadneEvent], None]] = []
        self._user_response_event = None
        self._user_response_payload: Any = None
        self.services = Services()

    def subscribe(self, listener: Callable[[AriadneEvent], None]):
        self._listeners.append(listener)

    def emit(self, event_type: str, payload: Any):
        event = AriadneEvent(type=event_type, payload=payload)
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass

    def transition(self, next_state: str):
        self.history.append(self.current_state)
        self.current_state = next_state
        self.emit("STATE_CHANGE", {"state": next_state, "history": self.history})

    def wait_for_user(self, timeout: Optional[float] = None) -> Any:
        if self._user_response_event is None:
            import threading

            self._user_response_event = threading.Event()
        self._user_response_event.clear()
        self._user_response_event.wait(timeout=timeout)
        return self._user_response_payload

    def submit_user_response(self, payload: Any):
        self._user_response_payload = payload
        if self._user_response_event:
            self._user_response_event.set()
