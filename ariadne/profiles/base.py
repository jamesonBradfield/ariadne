import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple, List, Dict, TYPE_CHECKING
from ariadne.components import TreeSitterSensor

if TYPE_CHECKING:
    from ariadne.core import EngineContext

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

    def get_standard_headers(self) -> str:
        """Returns standard headers/imports to prepend to generated tests."""
        return ""

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

    def get_all_symbols_patterns(self) -> List[Tuple[str, str]]:
        """Return a list of (pattern, meta_var_name) to find all symbols."""
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

    @abstractmethod
    def get_parent_block(
        self, filepath: str, byte_offset: int, context: "EngineContext"
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Finds the nearest 'logical parent' (class/impl/mod) containing a byte."""
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

    def find_symbol(
        self, filepath: str, symbol_name: str, context: "EngineContext"
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Finds all occurrences of a symbol in a file, preferring ast-grep if available."""
        if self.ast_grep_lang:
            from ariadne.primitives import QueryAstGrep

            querier = QueryAstGrep(self.ast_grep_lang)
            patterns = self.get_symbol_patterns(symbol_name)
            all_matches = []
            for pattern in patterns:
                status, matches = querier.tick(
                    {"filepath": filepath, "pattern": pattern}, context
                )
                if status == "SUCCESS":
                    all_matches.extend(matches)

            if all_matches:
                normalized = []
                for m in all_matches:
                    normalized.append(
                        {
                            "code": m["text"],
                            "start_byte": m["start_byte"],
                            "end_byte": m["end_byte"],
                            "type": m["node_type"],
                        }
                    )
                return "SUCCESS", normalized

        try:
            with open(filepath, "rb") as f:
                source = f.read()
            query = self.get_symbol_query(symbol_name)
            nodes = self.sensor.query_nodes(source, query, self.symbol_capture_name)
            return "SUCCESS", nodes
        except Exception as e:
            logger.error(f"Failed to find symbol {symbol_name} in {filepath}: {e}")
            return "ERROR", []

    def get_available_symbols(
        self, filepaths: List[str], context: "EngineContext"
    ) -> List[str]:
        """Returns a list of all function/class symbols available in the targets."""
        if self.ast_grep_lang:
            from ariadne.primitives import QueryAstGrep

            querier = QueryAstGrep(self.ast_grep_lang)
            patterns = self.get_all_symbols_patterns()
            all_symbols = set()

            for filepath in filepaths:
                if not os.path.exists(filepath):
                    continue
                for pattern, meta_var in patterns:
                    status, matches = querier.tick(
                        {"filepath": filepath, "pattern": pattern, "vars": [meta_var]},
                        context,
                    )
                    if status == "SUCCESS":
                        for m in matches:
                            name = m.get("vars", {}).get(meta_var)
                            if name:
                                all_symbols.add(name)
            return list(all_symbols)

        return []


class DynamicProfile(BaseProfile):
    """
    A data-driven profile that loads its configuration from JSON.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__()
        self._config = config
        self._language_ptr = None

    @property
    def name(self) -> str:
        return self._config.get("name", "Unknown")

    @property
    def extensions(self) -> List[str]:
        return self._config.get("extensions", [])

    def get_standard_headers(self) -> str:
        return self._config.get("standard_headers", "")

    def get_test_runner_script(self) -> str:
        test_runner = self._config.get("test_runner", {})
        return test_runner.get("script", "")

    def get_test_standard_headers(self) -> str:
        test_runner = self._config.get("test_runner", {})
        return test_runner.get("standard_headers", "")

    def get_test_command_template(self) -> str:
        return self._config.get(
            "test_command_template", "python {script} {target} {contract}"
        )

    def get_language_ptr(self) -> Any:
        if self._language_ptr is None:
            lang_id = self._config.get("language_id")
            if not lang_id:
                raise ValueError(f"Profile '{self.name}' missing 'language_id'")

            # Try to dynamically import the language package
            # e.g., language_id='rust' -> import tree_sitter_rust
            pkg_name = f"tree_sitter_{lang_id}"
            try:
                import importlib

                module = importlib.import_module(pkg_name)
                # Usually has a .language() or similarly named function
                # Some might use .language() some might use .language_id()
                # tree_sitter_rust uses .language()
                if hasattr(module, "language"):
                    self._language_ptr = module.language()
                else:
                    # Fallback for older patterns
                    self._language_ptr = getattr(module, lang_id)()
            except ImportError:
                logger.error(f"Failed to import tree-sitter package: {pkg_name}")
                raise
        return self._language_ptr

    @property
    def ast_grep_lang(self) -> Optional[str]:
        return self._config.get("ast_grep_lang")

    def get_skeleton_query(self) -> str:
        return self._config.get("tree_sitter_queries", {}).get("skeleton", "")

    def get_symbol_patterns(self, symbol_name: str) -> List[str]:
        patterns = self._config.get("ast_grep_patterns", {}).get("symbol", [])
        return [p.replace("{symbol_name}", symbol_name) for p in patterns]

    def get_all_symbols_patterns(self) -> List[Tuple[str, str]]:
        patterns = self._config.get("ast_grep_patterns", {}).get("all_symbols", [])
        # Expects list of [pattern, var]
        return [(p[0], p[1]) for p in patterns]

    def get_symbol_query(self, symbol_name: str) -> str:
        query = self._config.get("tree_sitter_queries", {}).get("symbol", "")
        return query.replace("{symbol_name}", symbol_name)

    @property
    def symbol_capture_name(self) -> str:
        return self._config.get("symbol_capture_name", "symbol")

    def get_parent_block(
        self, filepath: str, byte_offset: int, context: "EngineContext"
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        try:
            with open(filepath, "rb") as f:
                source = f.read()

            tree = self.sensor.parser.parse(source)
            node = tree.root_node.descendant_for_byte_range(byte_offset, byte_offset)

            parent_types = self._config.get("parent_block_types", [])

            curr = node
            while curr:
                if curr.type in parent_types:
                    return "SUCCESS", {
                        "code": curr.text.decode("utf-8"),
                        "start_byte": curr.start_byte,
                        "end_byte": curr.end_byte,
                        "type": curr.type,
                    }
                curr = curr.parent
            return "ERROR", None
        except Exception as e:
            logger.error(f"get_parent_block error: {e}")
            return "ERROR", None
