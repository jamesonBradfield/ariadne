from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Union

# --- LLM Response Models ---

class RouterResponse(BaseModel):
    reasoning: str
    next_state: str

class DispatchResponse(BaseModel):
    test_code: str

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

class SelfOptimizationResponse(BaseModel):
    id: str
    state: str
    intent: str
    current_symbol: str = ""
    error_context: str = ""
    ast_view: str = ""
    node_snippet: str = ""
    hover_info: str = ""
    diagnostics: str = ""
    expected_action: str
    expected_target_id: Optional[Union[str, int]] = None
    anti_expected_action: str

class InteractionTrace(BaseModel):
    state: str
    user_prompt: str
    system_prompt: str
    response: str

# --- Engine Payload ---

class JobPayload(BaseModel):
    """
    Data carried between states in the Ariadne HFSM.
    Contains ONLY transient, state-specific data.
    """
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
    
    # Engine progress
    retry_count: int = 0
    
    # Human-in-the-loop triggers
    needs_elaboration: bool = False
    failing_file: Optional[str] = None
    failing_line: Optional[str] = None
    next_headless_state: str = "ROUTER"
