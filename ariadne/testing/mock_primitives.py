import json
import logging
from typing import Any, Dict, Optional, Tuple
from ariadne.core import State

logger = logging.getLogger("ariadne.testing")

class MockQueryLLM(State):
    """
    A mock LLM primitive for deterministic testing.
    Matches the signature of ariadne.primitives.QueryLLM.
    """
    def __init__(self, model: Optional[str] = None, api_base: Optional[str] = None, responses: Optional[Dict[str, Any]] = None):
        super().__init__("MOCK_QUERY_LLM")
        self.model = model
        self.api_base = api_base
        self.responses = responses or {}

    def tick(self, payload: Dict[str, Any]) -> Tuple[str, Any]:
        """
        Matches QueryLLM.tick signature.
        """
        # The prompt suggests mapping state names (like 'MAPS') to responses.
        # We can also attempt to look at system prompt or user prompt to find the state.
        
        system = payload.get("system", "")
        
        # If we have a direct mapping for the state name, use it.
        # We'll default to 'MAPS' if nothing else matches.
        state_name = "MAPS"
        
        # In a real scenario, we might want to be more specific.
        # But for the task, a simple mapping is requested.
        response = self.responses.get(state_name)
        
        if response:
            return "SUCCESS", response
            
        return "ERROR", f"No mock response found for state {state_name}"
