import logging
from typing import Any, Dict, List, Optional

import tree_sitter

logger = logging.getLogger("ariadne.components")


class TreeSitterSensor:
    """
    A language-agnostic sensor that queries an AST and extracts raw byte coordinates.
    """

    def __init__(self, language_ptr):
        # We pass the language in (e.g., tree_sitter_rust.language()) so this
        # component remains 100% universal.
        try:
            self.language = tree_sitter.Language(language_ptr)
        except Exception:
            self.language = language_ptr
        self.parser = tree_sitter.Parser(self.language)

    def extract_node(
        self, filepath: str, query_string: str, capture_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Reads the file, runs the query, and returns the exact physical coordinates of the target.
        """
        logger.debug(f"[SENSOR] Query string: {query_string}")
        with open(filepath, "rb") as f:
            source_code = f.read()

        logger.debug(f"[SENSOR] Source code length: {len(source_code)} bytes")
        tree = self.parser.parse(source_code)
        query = tree_sitter.Query(self.language, query_string)

        query_cursor = tree_sitter.QueryCursor(query)
        captures = query_cursor.captures(tree.root_node)

        logger.debug(f"[SENSOR] Captures found: {captures}")

        target_node = None
        if isinstance(captures, dict):
            if capture_name in captures and captures[capture_name]:
                target_node = captures[capture_name][0]
        else:
            for node, name in captures:
                if name == capture_name:
                    target_node = node
                    break

        if target_node:
            return {
                "start_byte": target_node.start_byte,
                "end_byte": target_node.end_byte,
                "node_string": source_code[
                    target_node.start_byte : target_node.end_byte
                ].decode("utf8"),
                "full_source": source_code,  # We pass this along so the actuator doesn't have to re-read the disk
            }

        return None


class SubprocessSensor:
    """
    A simple wrapper around subprocess.run to provide structured output.
    """

    def __init__(self, command: List[str]):
        self.command = command

    def execute(self) -> Dict[str, Any]:
        """
        Executes the command and returns a dictionary with the results.
        """
        import subprocess

        try:
            # shell=False is safer for list-based commands
            result = subprocess.run(
                self.command, shell=False, capture_output=True, text=True, timeout=120
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
            }


class SyntaxGate:
    """
    A component that uses Tree-sitter to verify that a string is valid code.
    """

    def __init__(self, language_ptr):
        self.language = tree_sitter.Language(language_ptr)
        self.parser = tree_sitter.Parser(self.language)

    def validate(self, code_string: str) -> Dict[str, Any]:
        if "```" in code_string:
            return {
                "valid": False,
                "error_message": "Code contains markdown backticks (LLM leak)",
                "parsed_tree": None,
            }
        
        try:
            # Parse the code string
            tree = self.parser.parse(bytes(code_string, "utf8"))

            # Check if there are any syntax errors by looking for ERROR nodes
            def has_error_node(node):
                if node.type == "ERROR":
                    return True
                for child in node.children:
                    if has_error_node(child):
                        return True
                return False

            has_errors = has_error_node(tree.root_node)

            return {
                "valid": not has_errors,
                "error_message": "Syntax error detected in code"
                if has_errors
                else None,
                "parsed_tree": tree if not has_errors else None,
            }
        except Exception as e:
            return {
                "valid": False,
                "error_message": f"Failed to parse code: {str(e)}",
                "parsed_tree": None,
            }
