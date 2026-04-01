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

    def get_available_symbols(self, filepaths: List[str]) -> List[str]:
        """
        Extracts all function and class names from the target files.
        """
        query = """
        (function_definition name: (identifier) @name)
        (class_definition name: (identifier) @name)
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
