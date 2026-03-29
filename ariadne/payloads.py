from dataclasses import dataclass, field
from typing import List, Any, Optional, Dict

@dataclass
class JobPayload:
    input: str = ""
    intent: str = ""
    read_only_tests: List[str] = field(default_factory=list)
    target_files: List[str] = field(default_factory=list)
    current_file_index: int = 0
    target_symbols: List[str] = field(default_factory=list)
    extracted_nodes: List[Dict[str, Any]] = field(default_factory=list)
    extracted_context: List[str] = field(default_factory=list)
    test_stdout: str = ""
    llm_feedback: str = ""
    retry_count: int = 0
    fixed_code: Any = None
    plan: Dict[str, Any] = field(default_factory=dict)
    plan_history: List[str] = field(default_factory=list)
