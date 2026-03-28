import re
from typing import Any, Optional
import tree_sitter_python
from .base import LanguageProfile


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
        Construct a tree-sitter query to find a named item (function, class, etc.).
        """
        return f"""
        [
          (function_definition name: (identifier) @symbol_name (#eq? @symbol_name "{symbol_name}"))
          (class_definition name: (identifier) @symbol_name (#eq? @symbol_name "{symbol_name}"))
        ] @node
        """

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
    def target_capture_name(self) -> str:
        return "node"

    @property
    def coding_example(self) -> str:
        return (
            '{\n'
            '  "edits": [\n'
            '    {\n'
            '      "symbol": "process_data",\n'
            '      "new_code": "def process_data():\\n    pass"\n'
            '    }\n'
            '  ]\n'
            '}'
        )

    @property
    def check_command(self) -> list[str]:
        # Using the project-local venv for validation
        return [".\\.venv\\Scripts\\python.exe", "-m", "py_compile"]
