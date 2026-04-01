import tree_sitter_rust as tsrust
from typing import Any, List, Dict
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
            f"struct {symbol_name} {{ $$$ }}",
            f"struct {symbol_name}($$$);",
            f"impl {symbol_name} {{ $$$ }}",
            f"impl $$$ for {symbol_name} {{ $$$ }}"
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

    def get_available_symbols(self, filepaths: List[str]) -> List[str]:
        """
        Extracts all function and struct names from the target files.
        """
        query = """
        (function_item name: (identifier) @name)
        (struct_item name: (type_identifier) @name)
        (impl_item type: (type_identifier) @name)
        """
        symbols = []
        for path in filepaths:
            try:
                with open(path, "rb") as f:
                    source = f.read()
                nodes = self.sensor.query_nodes(source, query, "name")
                symbols.extend([n["code"] for n in nodes])
            except Exception:
                continue
        return list(set(symbols))
