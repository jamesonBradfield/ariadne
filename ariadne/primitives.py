import json
import logging
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import tree_sitter

from .core import State

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
            # Some tree-sitter versions return a dict of {name: [nodes]}
            # Others return a list of (node, name) tuples.
            captures = query_cursor.captures(tree.root_node)
            
            if isinstance(captures, dict):
                # Dict-based captures (newer API)
                if capture_name in captures:
                    for node in captures[capture_name]:
                        results.append(
                            source_code[node.start_byte : node.end_byte].decode("utf-8")
                        )
            else:
                # Tuple-based captures (older/standard API)
                for capture_item in captures:
                    if isinstance(capture_item, tuple) and len(capture_item) == 2:
                        node, name = capture_item
                        if name == capture_name:
                            results.append(
                                source_code[node.start_byte : node.end_byte].decode("utf-8")
                            )

            return "SUCCESS" if results else "NOT_FOUND", results
        except Exception as e:
            logger.error(f"ExtractAST Error: {e}")
            return "ERROR", [str(e)]


class QueryLLM(State):
    """
    Agnostic LLM query primitive.
    Input Payload: Dict with 'system', 'user', 'params', and 'post_process'.
    Returns: Tuple[str, Any] (status, processed_content)
    """

    def __init__(self, model: Optional[str] = None, api_base: Optional[str] = None):
        import os
        super().__init__("QUERY_LLM")

        # 1. Prioritize passed args, then Env, then local defaults
        self.api_base = (
            api_base or os.getenv("ARIADNE_API_BASE") or "http://localhost:8080/v1"
        )

        default_model = (
            "openai/llama-cpp" if "localhost" in self.api_base else "ollama/llama3"
        )
        self.model = model or os.getenv("ARIADNE_MODEL") or default_model
        
        # Ensure openai/ prefix if hitting localhost to trigger OpenAI provider in litellm
        if "localhost" in self.api_base and not self.model.startswith("openai/"):
            self.model = f"openai/{self.model}"

        # Only use API key if provided, otherwise 'none' for local servers
        self.api_key = os.getenv("ARIADNE_API_KEY") or "none"

    def tick(self, payload: Dict[str, Any]) -> Tuple[str, Any]:
        import litellm
        import re

        system = payload.get("system", "")
        user = payload.get("user", "")
        params = payload.get("params", {})
        post_process = payload.get("post_process")

        logger.info(f"[LLM REQUEST] System Prompt: {system}")
        logger.info(f"[LLM REQUEST] User Prompt: {user}")

        # Robustness: Combine system and user for local servers if needed
        if "localhost" in self.api_base:
            messages = [{"role": "user", "content": f"SYSTEM: {system}\n\nUSER: {user}"}]
        else:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]

        try:
            # Prepare arguments
            completion_args = {
                "model": self.model,
                "messages": messages,
                "api_base": self.api_base,
                "timeout": 300,
            }
            completion_args.update(params)
            
            if self.api_key:
                completion_args["api_key"] = self.api_key
            
            # Handle litellm's specific JSON mode if requested via params or post_process
            # DISABLE for local servers as it often causes empty responses
            if post_process == "extract_json" and "localhost" not in self.api_base:
                 completion_args["response_format"] = {"type": "json_object"}

            response = litellm.completion(**completion_args)
            content = response.choices[0].message.content
            
            logger.info(f"[LLM RESPONSE] Raw Content: {content}")

            # Post-Processing Logic
            if post_process == "extract_json":
                # Robust extraction: find the outermost { } pair
                # This must happen BEFORE stripping <think> tokens just in case
                # the model provided a valid JSON but put it inside/after think
                start_index = content.find("{")
                if start_index != -1:
                    bracket_count = 0
                    for i in range(start_index, len(content)):
                        if content[i] == "{":
                            bracket_count += 1
                        elif content[i] == "}":
                            bracket_count -= 1
                            if bracket_count == 0:
                                json_str = content[start_index : i + 1]
                                try:
                                    return "SUCCESS", json.loads(json_str)
                                except json.JSONDecodeError:
                                    break
                
                # Strip thinking tokens if present (common in Qwen models) and try again
                cleaned_content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                try:
                    return "SUCCESS", json.loads(cleaned_content)
                except json.JSONDecodeError:
                    return "JSON_ERROR", content

            if post_process == "strip_markdown":
                # Strip thinking tokens if present
                cleaned_content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                code_match = re.search(r"```(?:\w+)?\n(.*?)\n```", cleaned_content, re.DOTALL)
                if code_match:
                    return "SUCCESS", code_match.group(1).strip()
                return "SUCCESS", cleaned_content.strip("`").strip()

            return "SUCCESS", content
        except Exception as e:
            logger.error(f"QueryLLM Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
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


class ASTSplice(State):
    """
    Surgical AST-based splicing primitive.
    Input Payload: Dict with 'filepath' and 'edits' (list of dicts with 'start_byte', 'end_byte', 'new_code').
    Returns: Tuple[str, str] (status, filepath)
    """

    def __init__(self):
        super().__init__("AST_SPLICE")

    def tick(self, payload: Dict[str, Any]) -> Tuple[str, str]:
        filepath = payload.get("filepath")
        edits = payload.get("edits", [])

        if not edits:
            return "SUCCESS", filepath

        # Sort edits in reverse order (bottom-up) to prevent byte offset corruption
        edits.sort(key=lambda x: x["start_byte"], reverse=True)

        try:
            with open(filepath, "rb") as f:
                full_source = f.read()

            new_source_code = full_source

            for edit in edits:
                new_code = edit["new_code"]
                if "```" in new_code:
                    logger.error("ASTSplice rejected: Code contains markdown backticks.")
                    return "REJECTED", "Markdown detected"

                new_code_bytes = new_code.encode("utf-8")
                start_byte = edit["start_byte"]
                end_byte = edit["end_byte"]

                before = new_source_code[:start_byte]
                after = new_source_code[end_byte:]
                new_source_code = before + new_code_bytes + after

            with open(filepath, "wb") as f:
                f.write(new_source_code)

            return "SUCCESS", filepath
        except Exception as e:
            logger.error(f"ASTSplice Error: {e}")
            return "ERROR", str(e)
