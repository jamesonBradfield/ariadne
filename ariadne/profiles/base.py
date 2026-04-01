import logging
from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple, List, Dict
from ariadne.components import TreeSitterSensor

logger = logging.getLogger("ariadne.profiles")

class BaseProfile(ABC):
    """
    Base class for language-specific configurations in Ariadne.
    Encapsulates Tree-sitter queries and high-level AST operations.
    """

    def __init__(self):
        self._sensor: Optional[TreeSitterSensor] = None

    @property
    def sensor(self) -> TreeSitterSensor:
        if self._sensor is None:
            self._sensor = TreeSitterSensor(self.get_language_ptr())
        return self._sensor

    @property
    @abstractmethod
    def name(self) -> str:
        """The display name of the language (e.g., 'Rust')."""
        pass

    @property
    @abstractmethod
    def extensions(self) -> List[str]:
        """List of file extensions supported by this profile (e.g., ['.rs'])."""
        pass

    @abstractmethod
    def get_language_ptr(self) -> Any:
        """Return the tree-sitter language object/pointer."""
        pass

    @property
    def ast_grep_lang(self) -> Optional[str]:
        """Return the ast-grep language string (e.g., 'rust', 'python')."""
        return None

    @abstractmethod
    def get_skeleton_query(self) -> str:
        """Return the Tree-sitter query string to find bodies to strip for skeletonization."""
        pass

    def get_symbol_patterns(self, symbol_name: str) -> List[str]:
        """Return a list of ast-grep patterns to find the target symbol."""
        return []

    @abstractmethod
    def get_symbol_query(self, symbol_name: str) -> str:
        """Return the Tree-sitter query string to find the target symbol."""
        pass

    @property
    @abstractmethod
    def symbol_capture_name(self) -> str:
        """The Tree-sitter capture name for target symbols (e.g., 'function')."""
        pass

    def get_skeleton(self, filepath: str) -> Tuple[str, str]:
        """Generates a skeleton of the file by stripping function bodies."""
        try:
            with open(filepath, "rb") as f:
                source = f.read()
            skeleton = self.sensor.skeletonize(source, self.get_skeleton_query())
            return "SUCCESS", skeleton
        except Exception as e:
            logger.error(f"Failed to generate skeleton for {filepath}: {e}")
            return "ERROR", str(e)

    def find_symbol(self, filepath: str, symbol_name: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Finds all occurrences of a symbol in a file, preferring ast-grep if available."""
        if self.ast_grep_lang:
            from ariadne.primitives import QueryAstGrep
            querier = QueryAstGrep(self.ast_grep_lang)
            patterns = self.get_symbol_patterns(symbol_name)
            all_matches = []
            for pattern in patterns:
                status, matches = querier.tick({"filepath": filepath, "pattern": pattern})
                if status == "SUCCESS":
                    # Filter matches by checking if the text actually contains the symbol name 
                    # (ast-grep patterns like 'fn $NAME' might be too broad if not careful)
                    # But here we assume patterns are specific enough or we rely on ast-grep's precision.
                    all_matches.extend(matches)
            
            if all_matches:
                # Normalize to Tree-sitter node format used by states
                normalized = []
                for m in all_matches:
                    normalized.append({
                        "code": m["text"],
                        "start_byte": m["start_byte"],
                        "end_byte": m["end_byte"],
                        "type": m["node_type"]
                    })
                return "SUCCESS", normalized

        # Fallback to Tree-sitter
        try:
            with open(filepath, "rb") as f:
                source = f.read()
            query = self.get_symbol_query(symbol_name)
            nodes = self.sensor.query_nodes(source, query, self.symbol_capture_name)
            return "SUCCESS", nodes
        except Exception as e:
            logger.error(f"Failed to find symbol {symbol_name} in {filepath}: {e}")
            return "ERROR", []

    def get_available_symbols(self, filepaths: List[str]) -> List[str]:
        """Returns a list of all function/class symbols available in the targets."""
        all_symbols = []
        # This is a simplified version; usually we'd have a 'list all symbols' query
        # For now, we'll return an empty list or implement a basic 'all_functions' query in profiles
        return all_symbols
