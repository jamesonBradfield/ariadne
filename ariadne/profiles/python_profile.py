import tree_sitter_python as tspython
from typing import Any, List
from .base import BaseProfile

class PythonProfile(BaseProfile):
    """
    Python-specific profile for Ariadne.
    """

    @property
    def name(self) -> str:
        return "Python"

    @property
    def extensions(self) -> List[str]:
        return [".py"]

    def get_language_ptr(self) -> Any:
        return tspython.language()

    @property
    def ast_grep_lang(self) -> str:
        return "python"

    def get_symbol_patterns(self, symbol_name: str) -> List[str]:
        """
        Patterns to find a specific function or class by name.
        """
        return [
            f"def {symbol_name}($$$): $$$",
            f"class {symbol_name}: $$$",
            f"class {symbol_name}($$$): $$$"
        ]

    def get_all_symbols_patterns(self) -> List[Tuple[str, str]]:
        """
        Patterns to find all functions and classes.
        """
        return [
            ("def $NAME($$$): $$$", "$NAME"),
            ("class $NAME: $$$", "$NAME"),
            ("class $NAME($$$): $$$", "$NAME")
        ]

    def get_skeleton_query(self) -> str:

        """
        Query to find function/method/class bodies for skeletonization.
        """
        return """
        (function_definition body: (block) @body)
        (class_definition body: (block) @body)
        """

    def get_symbol_query(self, symbol_name: str) -> str:
        """
        Query to find a specific function or class by name.
        """
        return f"""
        (function_definition
            name: (identifier) @name
            (#eq? @name "{symbol_name}")
        ) @symbol

        (class_definition
            name: (identifier) @name
            (#eq? @name "{symbol_name}")
        ) @symbol
        """

    @property
    def symbol_capture_name(self) -> str:
        return "symbol"
