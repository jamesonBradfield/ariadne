import tree_sitter_rust as tsrust
from typing import Any, List
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

    def get_skeleton_query(self) -> str:
        """
        Query to find function/method bodies for skeletonization.
        """
        return """
        (function_item (block) @body)
        (function_signature_item) @item
        (impl_item (block) @body)
        """

    def get_symbol_query(self, symbol_name: str) -> str:
        """
        Query to find a specific function or method by name.
        """
        return f"""
        (function_item
            name: (identifier) @name
            (#eq? @name "{symbol_name}")
        ) @symbol

        (impl_item
            name: (identifier) @name
            (#eq? @name "{symbol_name}")
        ) @symbol
        """

    @property
    def symbol_capture_name(self) -> str:
        return "symbol"

    def get_available_symbols(self, filepaths: List[str]) -> List[str]:
        """
        Extracts all function and method names from the target files.
        """
        query = """
        (function_item name: (identifier) @name)
        (impl_item name: (identifier) @name)
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
