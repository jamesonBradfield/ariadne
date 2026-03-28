import re
from typing import Any, Optional
import tree_sitter_python
from profiles.base import LanguageProfile


class PythonProfile(LanguageProfile):
    """
    Profile for Python, providing tree-sitter queries and build commands.
    """

    @property
    def name(self) -> str:
        return "Python"

    @property
    def extensions(self) -> list[str]:
        return [".py"]

    def get_language_ptr(self) -> Any:
        return tree_sitter_python.language()

    def get_query(self, symbol_name: str) -> str:
        """
        Construct a tree-sitter query to find a function or class definition by name.
        """
        return (
            f'([\n'
            f'  (function_definition name: (identifier) @name)\n'
            f'  (class_definition name: (identifier) @name)\n'
            f'] (#eq? @name "{symbol_name}")) @target'
        )

    @property
    def target_capture_name(self) -> str:
        return "target"

    def get_skeleton_query(self) -> str:
        """
        Return the query to find function bodies to strip for skeletonization.
        """
        return "(function_definition body: (block) @body) @func"

    @property
    def skeleton_capture_name(self) -> str:
        return "func"

    @property
    def test_generation_system_prompt(self) -> str:
        return (
            "You are a Python testing expert. Your sole task is to generate isolated Python unit tests using `pytest` or `unittest`.\n"
            "The code provided in the context (`Context API Surface`) defines the available classes and functions.\n"
            "Your output MUST contain ONLY test functions or classes.\n"
            "DO NOT include any of the original implementation code.\n"
            "Output RAW PYTHON CODE ONLY. No markdown, no explanations."
        )

    @property
    def search_system_prompt(self) -> str:
        return (
            "You are a Python architect. Analyze the test error and the project skeletons.\n"
            "Identify the specific function or class names that need to be modified or inspected.\n"
            "Return a JSON object with a 'nodes' array of strings (e.g., ['MyClass', 'process_data'])."
        )

    @property
    def coding_system_prompt(self) -> str:
        return (
            f"You are an expert Python developer. You act as a surgical execution engine.\n"
            f"You MUST output ONLY a SINGLE valid JSON object. No markdown, no conversational text.\n"
            f"The JSON object MUST contain exactly one key called 'edits', which is an array of objects.\n"
            f"Example:\n"
            f'{{\n  "edits": [\n    {{"symbol": "process_data", "new_code": "def process_data():\\n    pass"}}\n  ]\n}}\n'
            f"Provide the exact rewritten code for each requested symbol."
        )

    def parse_search_result(self, response: str) -> Optional[str]:
        """
        Parse the LLM's raw response to extract the function/item name.
        """
        target_name = response.strip()

        # Try to extract just the function name (e.g., from 'def my_func')
        fn_match = re.search(r"def\s+(\w+)", target_name)
        if fn_match:
            return fn_match.group(1)

        # Basic sanitization: take the first line, strip whitespace
        target_name = target_name.split("\n")[0].strip()
        return target_name if target_name else None

    @property
    def check_command(self) -> list[str]:
        # Using the project-local venv for validation
        return [".\\.venv\\Scripts\\python.exe", "-m", "py_compile"]
