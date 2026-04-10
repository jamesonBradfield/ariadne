import tree_sitter_rust as tsrust
from typing import Any, List, Dict, Tuple, Optional
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

    def get_parent_block(self, filepath: str, byte_offset: int) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Finds the nearest impl_item or mod_item containing the byte."""
        try:
            with open(filepath, "rb") as f:
                source = f.read()
            
            tree = self.sensor.parser.parse(source)
            node = tree.root_node.descendant_for_byte_range(byte_offset, byte_offset)
            
            # Walk up to find impl_item, mod_item, or trait_item
            curr = node
            while curr:
                if curr.type in ["impl_item", "mod_item", "trait_item", "declaration_list"]:
                    return "SUCCESS", {
                        "code": curr.text.decode("utf-8"),
                        "start_byte": curr.start_byte,
                        "end_byte": curr.end_byte,
                        "type": curr.type
                    }
                curr = curr.parent
            return "ERROR", None
        except Exception as e:
            return "ERROR", None
