from dataclasses import dataclass, field
from typing import List, Any


@dataclass
class ContextPayload:
    raw_prompt: str
    live_runtime_data: Any
    project_skeleton: str


@dataclass
class JobPayload:
    intent: str
    read_only_tests: List[str] = field(default_factory=list)
    target_files: List[str] = field(default_factory=list)
    current_file_index: int = 0
    extracted_context: List[str] = field(default_factory=list)
    test_stdout: str = ""
    llm_feedback: str = ""
    retry_count: int = 0
