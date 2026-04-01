import logging
from typing import Any, List, Dict, Tuple, Optional
from tree_sitter import Parser, Language, Tree, Node

logger = logging.getLogger("ariadne.components")

class TreeSitterSensor:
    """
    High-level AST observer and validator using Tree-sitter.
    """
    def __init__(self, language_ptr: Any):
        self.language = Language(language_ptr)
        self.parser = Parser(self.language)

    def skeletonize(self, source: bytes, query_str: str) -> str:
        """
        Strips function/method bodies based on a query to create a file skeleton.
        """
        tree = self.parser.parse(source)
        query = self.language.query(query_str)
        captures = query.captures(tree.root_node)
        
        # We want to find bodies to replace with "{ ... }"
        # Usually capture names like @body
        edits = []
        for node, name in captures:
            if name == "body":
                edits.append((node.start_byte, node.end_byte, b" { ... }"))
            elif name == "item" and not any(n == "body" for _, n in captures):
                # If we captured an item but no body (like a signature), we keep it
                pass

        # Sort edits in reverse order to maintain offset integrity
        edits.sort(key=lambda x: x[0], reverse=True)
        
        result = bytearray(source)
        for start, end, replacement in edits:
            result[start:end] = replacement
            
        return result.decode("utf-8")

    def query_nodes(self, source: bytes, query_str: str, capture_name: str) -> List[Dict[str, Any]]:
        """
        Executes a query and returns metadata for all nodes matching capture_name.
        """
        tree = self.parser.parse(source)
        query = self.language.query(query_str)
        captures = query.captures(tree.root_node)
        
        results = []
        for node, name in captures:
            if name == capture_name:
                results.append({
                    "code": node.text.decode("utf-8"),
                    "start_byte": node.start_byte,
                    "end_byte": node.end_byte,
                    "type": node.type
                })
        return results

    def validate_repair(self, source: bytes, edits: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
        """
        Checks if the proposed edits result in valid syntax.
        """
        # Apply edits in memory
        temp_source = bytearray(source)
        # Sort reverse for offset safety
        sorted_edits = sorted(edits, key=lambda x: x["start_byte"], reverse=True)
        
        for edit in sorted_edits:
            temp_source[edit["start_byte"]:edit["end_byte"]] = edit["new_code"].encode("utf-8")
            
        new_tree = self.parser.parse(bytes(temp_source))
        if new_tree.root_node.has_error:
            # Simple error detection
            return False, "Syntax error detected in the generated tree."
        return True, None

class SyntaxGate:
    """
    Validation component used by the SYNTAX_GATE state.
    """
    def __init__(self, profile):
        self.profile = profile
        self.sensor = TreeSitterSensor(profile.get_language_ptr())

    def verify(self, filepath: str, edits: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
        try:
            with open(filepath, "rb") as f:
                source = f.read()
            return self.sensor.validate_repair(source, edits)
        except Exception as e:
            return False, str(e)
