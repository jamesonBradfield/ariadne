import logging
import subprocess
from typing import Any, List, Dict, Tuple, Optional
import tree_sitter
from tree_sitter import Parser, Language, Tree, Node

logger = logging.getLogger("ariadne.components")

class TreeSitterSensor:
    """
    High-level AST observer and validator using Tree-sitter.
    """
    def __init__(self, language_ptr: Any):
        self.language = Language(language_ptr)
        self.parser = Parser(self.language)

    def _get_captures(self, root_node: Node, query_str: str) -> List[Tuple[Node, str]]:
        """
        Helper to handle both dict-based and list-based captures across tree-sitter versions.
        Returns a list of (node, capture_name) tuples.
        """
        query = tree_sitter.Query(self.language, query_str)
        cursor = tree_sitter.QueryCursor(query)
        captures = cursor.captures(root_node)
        
        normalized = []
        if isinstance(captures, dict):
            # Tree-sitter 0.25.2: Dict[str, List[Node]]
            for name, nodes in captures.items():
                for node in nodes:
                    normalized.append((node, name))
        else:
            # Older versions: List[Tuple[Node, str]] or List[Tuple[Node, str, int]]
            for item in captures:
                if isinstance(item, tuple):
                    # Unpack carefully
                    node = item[0]
                    name = item[1]
                    normalized.append((node, name))
        return normalized

    def skeletonize(self, source: bytes, query_str: str) -> str:
        """
        Strips function/method bodies based on a query to create a file skeleton.
        """
        tree = self.parser.parse(source)
        captures = self._get_captures(tree.root_node, query_str)
        
        edits = []
        for node, name in captures:
            if name == "body":
                edits.append((node.start_byte, node.end_byte, b" { ... }"))

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
        captures = self._get_captures(tree.root_node, query_str)
        
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

    def render_node_children(self, source: bytes, start_byte: int, end_byte: int) -> Tuple[str, Dict[int, Tuple[int, int]]]:
        """
        Parses a specific byte range and returns a rendered view of its immediate named children
        with temporary IDs, plus a mapping of those IDs to absolute (start, end) bytes.
        """
        # We parse the full source but focus on the node at the given range
        tree = self.parser.parse(source)
        
        # Find the smallest node that covers the requested range
        node = tree.root_node.descendant_for_byte_range(start_byte, end_byte)
        
        # If the descendant is the same as requested, or we want its children:
        view_lines = []
        id_map = {}
        
        # Header for the view
        view_lines.append(f"Current Node: {node.type} [{node.start_byte}-{node.end_byte}]")
        
        child_idx = 0
        for child in node.children:
            if not child.is_named:
                continue
                
            # Get a snippet of the child's code for the view (first line or truncated)
            child_code = child.text.decode("utf-8", errors="replace").split("\n")[0]
            if len(child_code) > 80:
                child_code = child_code[:77] + "..."
            
            view_lines.append(f"[{child_idx}] {child.type}: \"{child_code}\"")
            id_map[child_idx] = (child.start_byte, child.end_byte)
            child_idx += 1
            
        if not id_map:
            view_lines.append(" (No named children)")
            
        return "\n".join(view_lines), id_map

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

class SubprocessSensor:
    """
    Primitive for running shell commands and capturing output.
    Used by legacy hooks and profiles.
    """
    def __init__(self, command: List[str]):
        self.command = command

    def execute(self) -> Dict[str, Any]:
        try:
            res = subprocess.run(self.command, capture_output=True, text=True)
            return {
                "success": res.returncode == 0,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "returncode": res.returncode
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1
            }
