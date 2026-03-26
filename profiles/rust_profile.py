import re
from typing import Any, Optional
import tree_sitter_rust
from profiles.base import LanguageProfile


class RustProfile(LanguageProfile):
    """
    Profile for Rust, providing tree-sitter queries and build commands.
    """

    @property
    def name(self) -> str:
        return "Rust"

    @property
    def extensions(self) -> list[str]:
        return [".rs"]

    def get_language_ptr(self) -> Any:
        return tree_sitter_rust.language()

    def get_query(self, symbol_name: str) -> str:
        """
        Construct a tree-sitter query to find a function item by name.
        """
        return (
            f'(function_item name: (identifier) @func_name (#eq? @func_name "{symbol_name}")) @function'
        )

    def get_skeleton_query(self) -> str:
        """
        Return the query to find function bodies to strip for skeletonization.
        """
        return "(function_item body: (block) @body) @func"

    def parse_search_result(self, response: str) -> Optional[str]:
        """
        Parse the LLM's raw response to extract the function/item name.
        """
        target_name = response.strip()

        # Try to extract just the function name (e.g., from 'fn my_func')
        fn_match = re.search(r"fn\s+(\w+)", target_name)
        if fn_match:
            return fn_match.group(1)

        # Basic sanitization: take the first line, strip whitespace
        target_name = target_name.split("\n")[0].strip()
        return target_name if target_name else None

    @property
    def check_command(self) -> list[str]:
        return ["cargo", "check"]
