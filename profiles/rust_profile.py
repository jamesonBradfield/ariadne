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
        Construct a tree-sitter query to find a function, struct, or impl block by name.
        """
        return (
            f'([\n'
            f'  (function_item name: (identifier) @name)\n'
            f'  (struct_item name: (type_identifier) @name)\n'
            f'  (impl_item type: (type_identifier) @name)\n'
            f'] (#eq? @name "{symbol_name}")) @target'
        )

    @property
    def target_capture_name(self) -> str:
        return "target"

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

    @property
    def search_system_prompt(self) -> str:
        return (
            "You are a Rust architect. Analyze the test error and the project skeletons.\n"
            "Identify the specific function, struct, or impl block names that need to be modified or inspected.\n"
            "Return a JSON object with a 'nodes' array of strings (e.g., ['Entity', 'take_damage'])."
        )

    @property
    def coding_system_prompt(self) -> str:
        return (
            f"You are an expert Rust developer. You act as a surgical execution engine.\n"
            f"You MUST output a valid JSON object with an 'edits' key. Each edit must contain 'symbol' and 'new_code'.\n"
            f"Example:\n"
            f'{{"edits": [{{"symbol": "Entity", "new_code": "struct Entity {{ ... }}"}}]}}\n'
            f"Output ONLY the JSON object. No conversational text."
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
    def check_command(self) -> list[str]:
        return ["cargo", "check"]
