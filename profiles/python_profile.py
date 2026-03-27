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
        Construct a tree-sitter query to find a function definition by name.
        """
        return (
            f'(function_definition name: (identifier) @func_name (#eq? @func_name "{symbol_name}")) @function'
        )

    def get_skeleton_query(self) -> str:
        """
        Return the query to find function bodies to strip for skeletonization.
        """
        return "(function_definition body: (block) @body) @func"

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
