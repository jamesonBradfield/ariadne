import re
from typing import Any, Optional
import tree_sitter_rust
from .base import LanguageProfile


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
        Construct a tree-sitter query to find a named item (function, struct, etc.).
        """
        return f"""
        [
          (function_item name: (identifier) @symbol_name (#eq? @symbol_name "{symbol_name}"))
          (struct_item name: (type_identifier) @symbol_name (#eq? @symbol_name "{symbol_name}"))
          (enum_item name: (type_identifier) @symbol_name (#eq? @symbol_name "{symbol_name}"))
          (trait_item name: (type_identifier) @symbol_name (#eq? @symbol_name "{symbol_name}"))
          (type_item name: (type_identifier) @symbol_name (#eq? @symbol_name "{symbol_name}"))
        ] @node
        """

    def get_skeleton_query(self) -> str:
        """
        Return the query to find function bodies to strip for skeletonization.
        """
        return "(function_item body: (block) @body) @func"

    @property
    def skeleton_capture_name(self) -> str:
        return "func"

    @property
    def test_generation_system_prompt(self) -> str:
        return (
            "You are a Rust testing expert. Your sole task is to generate isolated Rust unit tests.\n"
            "The code provided in the context (`Context API Surface`) defines the available structs and functions.\n"
            "Your output MUST contain ONLY `#[test]` functions.\n"
            "DO NOT include any `struct` definitions.\n"
            "DO NOT include any `impl` blocks for methods.\n"
            "DO NOT include any `use` statements unless they are part of the test function itself.\n"
            "Output RAW RUST CODE ONLY. No markdown, no explanations."
        )

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
    def target_capture_name(self) -> str:
        return "node"

    @property
    def coding_example(self) -> str:
        return (
            '{\n'
            '  "edits": [\n'
            '    {\n'
            '      "symbol": "Entity",\n'
            '      "new_code": "struct Entity {\\n    health: f32,\\n}"\n'
            '    }\n'
            '  ]\n'
            '}'
        )

    @property
    def check_command(self) -> list[str]:
        return ["cargo", "check"]
