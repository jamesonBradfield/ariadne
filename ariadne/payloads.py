from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Union

# --- LLM Response Models ---

class RouterResponse(BaseModel):
    reasoning: str
    next_state: str

class ThinkingStep(BaseModel):
    symbol: str

class ThinkingResponse(BaseModel):
    reasoning: str
    steps: List[ThinkingStep]

class MapsNavResponse(BaseModel):
    reasoning: str
    action: str
    target_id: Union[str, int]

class MapsThinkResponse(BaseModel):
    reasoning: str
    action: str
    draft_code: str = ""

class MapsSurgeonResponse(BaseModel):
    reasoning: str
    action: str
    code: str = ""

# --- Engine Payload ---

class JobPayload(BaseModel):
    """
    Data carried between states in the Ariadne HFSM.
    Strict Pydantic model for validation and dot-notation access.
    """
    intent: str
    target_files: List[str] = Field(default_factory=list)
    
    # DISPATCH / EVALUATE outputs
    test_code: Optional[str] = None
    test_stdout: Optional[str] = None
    
    # THINKING / SEARCH outputs
    plan: Optional[ThinkingResponse] = None
    plan_history: List[str] = Field(default_factory=list)
    extracted_nodes: List[Dict[str, Any]] = Field(default_factory=list)
    docs: Optional[str] = None
    
    # MAPS / ACTUATE outputs
    maps_state: Dict[str, Any] = Field(default_factory=dict)
    fixed_code: Optional[Dict[str, Any]] = None
    llm_feedback: Optional[str] = None
    
    # Global state
    retry_count: int = 0
    app: Any = None # Reference to AriadneApp for TUI messages
    
    # Human-in-the-loop triggers
    needs_elaboration: bool = False
    failing_file: Optional[str] = None
    failing_line: Optional[str] = None
    next_headless_state: str = "ROUTER"

    class Config:
        arbitrary_types_allowed = True
