import tree_sitter_rust as tsrust
from typing import Any, List, Dict, Tuple
from .base import BaseProfile

class RustProfile(BaseProfile):
    """
    Rust-specific profile for Ariadne.
    """

    @property
    def name(self) -> str:
        return "Rust"

    @property
    def extensions(self) -> List[str]:
        return [".rs"]

    def get_standard_headers(self) -> str:
        """Inject godot-rust headers for testing."""
        return "use godot::prelude::*;\n"

    def get_language_ptr(self) -> Any:
        return tsrust.language()

    @property
    def ast_grep_lang(self) -> str:
        return "rust"

    def get_symbol_patterns(self, symbol_name: str) -> List[str]:
        """
        Patterns to find a specific function, method, or struct by name.
        """
        return [
            f"fn {symbol_name}($$$) {{ $$$ }}",
            f"fn {symbol_name}($$$) -> $$$ {{ $$$ }}",
            f"struct {symbol_name} {{ $$$ }}",
            f"struct {symbol_name}($$$);",
            f"impl {symbol_name} {{ $$$ }}",
            f"impl $$$ for {symbol_name} {{ $$$ }}"
        ]

    def get_all_symbols_patterns(self) -> List[Tuple[str, str]]:
        """
        Patterns to find all functions and structs.
        """
        return [
            ("fn $NAME($$$) { $$$ }", "$NAME"),
            ("fn $NAME($$$) -> $$$ { $$$ }", "$NAME"),
            ("struct $NAME { $$$ }", "$NAME"),
            ("impl $NAME { $$$ }", "$NAME")
        ]

    def get_skeleton_query(self) -> str:
        """
        Query to find function/method bodies for skeletonization.
        """
        return """
        (function_item (block) @body)
        """

    def get_symbol_query(self, symbol_name: str) -> str:
        """
        Query to find a specific function, method, or struct by name.
        """
        return f"""
        (function_item
            name: (identifier) @name
            (#eq? @name "{symbol_name}")
        ) @symbol

        (struct_item
            name: (type_identifier) @name
            (#eq? @name "{symbol_name}")
        ) @symbol

        (impl_item
            type: (type_identifier) @name
            (#eq? @name "{symbol_name}")
        ) @symbol
        """

    @property
    def symbol_capture_name(self) -> str:
        return "symbol"
