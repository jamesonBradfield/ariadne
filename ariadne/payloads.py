from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class JobPayload:
    """
    Data carried between states in the Ariadne HFSM.
    """
    intent: str
    target_files: List[str] = field(default_factory=list)
    
    # DISPATCH / EVALUATE outputs
    test_code: Optional[str] = None
    test_stdout: Optional[str] = None
    
    # THINKING / SEARCH outputs
    plan: Dict[str, Any] = field(default_factory=dict)
    plan_history: List[str] = field(default_factory=list)
    extracted_nodes: List[Dict[str, Any]] = field(default_factory=list)
    
    # MAPS / ACTUATE outputs
    maps_state: Dict[str, Any] = field(default_factory=dict)
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
