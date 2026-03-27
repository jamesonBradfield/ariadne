import json
import logging
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import tree_sitter

from core import State

logger = logging.getLogger("ariadne.primitives")


class ExtractAST(State):
    """
    Agnostic Tree-sitter extraction primitive.
    Input Payload: Dict with 'filepath', 'query_string', and 'capture_name'.
    Returns: Tuple[str, List[str]] (status, extracted_code_strings)
    """

    def __init__(self, language_ptr: Any):
        super().__init__("EXTRACT_AST")
        # Compatibility with various tree-sitter python binding versions
        try:
            self.language = tree_sitter.Language(language_ptr)
        except Exception:
            self.language = language_ptr

        self.parser = tree_sitter.Parser(self.language)

    def tick(self, payload: Dict[str, Any]) -> Tuple[str, List[str]]:
        filepath = payload.get("filepath")
        query_string = payload.get("query_string")
        capture_name = payload.get("capture_name", "node")

        if not filepath or not query_string:
            logger.warning(f"ExtractAST skipped: Missing filepath ({filepath}) or query_string ({query_string})")
            return "ERROR", []

        try:
            with open(filepath, "rb") as f:
                source_code = f.read()

            tree = self.parser.parse(source_code)
            # Create a Query object from the query_string
            query = tree_sitter.Query(self.language, query_string.encode("utf-8"))
            query_cursor = tree_sitter.QueryCursor(query)

            results = []  # Initialize results list
            # captures is an iterator of (node, name_str) tuples
            for capture_item in query_cursor.captures(tree.root_node):
                # Check if it's a tuple of length 2 before unpacking
                if isinstance(capture_item, tuple) and len(capture_item) == 2:
                    node, name = capture_item
                    if name == capture_name:
                        results.append(
                            source_code[node.start_byte : node.end_byte].decode("utf-8")
                        )
                else:
                    logger.warning(
                        f"Skipping malformed capture item in ExtractAST: {capture_item}"
                    )

            return "SUCCESS" if results else "NOT_FOUND", results
        except Exception as e:
            logger.error(f"ExtractAST Error: {e}")
            return "ERROR", [str(e)]


class QueryLLM(State):
    """
    Agnostic LLM query primitive.
    Input Payload: Dict with 'system', 'user', and optional 'schema'.
    Returns: Tuple[str, Any] (status, raw_string or parsed_json)
    """

    def __init__(self, model: Optional[str] = None, api_base: Optional[str] = None):
        super().__init__("QUERY_LLM")
        import os

        self.model = model or os.getenv("ARIADNE_MODEL") or "ollama/llama3"
        self.api_base = api_base or os.getenv("ARIADNE_API_BASE")
        self.api_key = os.getenv("ARIADNE_API_KEY") or "none"

    def tick(self, payload: Dict[str, Any]) -> Tuple[str, Any]:
        import litellm

        system = payload.get("system", "")
        user = payload.get("user", "")
        schema = payload.get("schema")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        try:
            response = litellm.completion(
                model=self.model,
                messages=messages,
                api_base=self.api_base,
                api_key=self.api_key,
                response_format={"type": "json_object"} if schema else None,
                temperature=0.0,
            )
            content = response.choices[0].message.content

            if schema:
                try:
                    return "SUCCESS", json.loads(content)
                except json.JSONDecodeError:
                    return "JSON_ERROR", content

            return "SUCCESS", content
        except Exception as e:
            logger.error(f"QueryLLM Error: {e}")
            return "ERROR", str(e)


class ExecuteCommand(State):
    """
    Agnostic shell execution primitive.
    Input Payload: str (the command)
    Returns: Tuple[str, str] (status, combined_output)
    """

    def __init__(self):
        super().__init__("EXECUTE_COMMAND")

    def tick(self, command: str) -> Tuple[str, str]:
        try:
            # shell=True for terminal-like behavior, timeout to prevent hanging
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=120
            )
            output = f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            status = "SUCCESS" if result.returncode == 0 else "FAILURE"
            return status, output
        except subprocess.TimeoutExpired:
            return "TIMEOUT", "Command timed out after 120s."
        except Exception as e:
            logger.error(f"ExecuteCommand Error: {e}")
            return "ERROR", str(e)


class PromptUser(State):
    """
    Agnostic user confirmation primitive.
    Input Payload: str (the proposal/message)
    Returns: Tuple[str, bool] (status, user_choice)
    """

    def __init__(self):
        super().__init__("PROMPT_USER")

    def tick(self, proposal: str) -> Tuple[str, bool]:
        print(f"\n[PROPOSAL]\n{proposal}\n")
        while True:
            choice = input("Proceed? (y/n): ").strip().lower()
            if choice in ["y", "yes"]:
                return "ACCEPTED", True
            if choice in ["n", "no"]:
                return "REJECTED", False
            print("Please enter 'y' or 'n'.")


class WriteFile(State):
    """
    Agnostic file writing primitive.
    Input Payload: Dict with 'filepath' and 'content'.
    Returns: Tuple[str, str] (status, filepath)
    """

    def __init__(self):
        super().__init__("WRITE_FILE")

    def tick(self, payload: Dict[str, str]) -> Tuple[str, str]:
        filepath = payload.get("filepath")
        content = payload.get("content")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return "SUCCESS", filepath
        except Exception as e:
            logger.error(f"WriteFile Error: {e}")
            return "ERROR", str(e)
