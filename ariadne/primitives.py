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
        # (Merging often bypasses "yapping" and truncation on local servers)
        if "localhost" in self.api_base:
            messages = [{"role": "user", "content": f"INSTRUCTIONS: {system}\n\nCONTEXT:\n{user}"}]
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
            }
            completion_args.update(params)
            
            if self.api_key:
                completion_args["api_key"] = self.api_key
            
            # Handle litellm's specific JSON mode if requested via params or post_process
            # DISABLE for local servers as it often causes empty responses
            if post_process == "extract_json" and "localhost" not in self.api_base:
                 completion_args["response_format"] = {"type": "json_object"}

            # Local server can be slow to load models
            import time
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = litellm.completion(**completion_args)
                    break
                except Exception as e:
                    if "503" in str(e) and attempt < max_retries - 1:
                        logger.warning(f"Server loading model (503). Retrying in 5s... (Attempt {attempt+1}/{max_retries})")
                        time.sleep(5)
                    else:
                        raise e

            # Extract content - prioritize standard message content
            message = response.choices[0].message
            content = message.content or ""
            
            # Log reasoning if present, but truncated
            r_log = ""
            if hasattr(message, "reasoning_content") and message.reasoning_content:
                r_log = message.reasoning_content
            elif isinstance(message, dict) and "reasoning_content" in message:
                r_log = message["reasoning_content"]
            
            if r_log:
                logger.info(f"[LLM REASONING] {r_log[:500]}... [TRUNCATED]")

            # Use reasoning_content ONLY if standard content is empty
            if not content and r_log:
                content = r_log

            # NUDGE NUDGE: If prompt ended with a bracket, put it back
            if user.endswith("{") and not content.startswith("{"):
                content = "{" + content

            logger.info(f"[LLM RESPONSE] Raw Choices: {response.choices}")
            logger.info(f"[LLM RESPONSE] Final Content: '{content}'")

            # Post-Processing Logic
            if post_process == "extract_json":
                # STRATEGY 1: Check for explicit separator
                if "--- JSON PLAN ---" in content:
                    content = content.split("--- JSON PLAN ---")[-1]

                # STRATEGY 2: Find all possible JSON blocks and pick the one that parses successfully
                import re
                
                # Find all candidates starting with { and ending with }
                candidates = []
                stack = []
                start = -1
                for i, char in enumerate(content):
                    if char == '{':
                        if not stack:
                            start = i
                        stack.append('{')
                    elif char == '}':
                        if stack:
                            stack.pop()
                            if not stack:
                                candidates.append(content[start:i+1])
                
                # Sort candidates by length (longest first usually has the full plan)
                candidates.sort(key=len, reverse=True)
                
                for cand in candidates:
                    try:
                        parsed = json.loads(cand)
                        # Optional: Validate schema here if needed
                        return "SUCCESS", parsed
                    except json.JSONDecodeError:
                        continue
                
                # TRUNCATION REPAIR (Fallback): If we have an open JSON but it's truncated
                # Only if the server still cut us off despite the high limit
                if stack:
                    logger.warning("Detected truncated JSON, attempting repair...")
                    repaired_json = content[start:] + "}" * len(stack)
                    try:
                        return "SUCCESS", json.loads(repaired_json)
                    except Exception:
                        pass

                return "JSON_ERROR", content

            if post_process == "strip_markdown":
                code_match = re.search(r"```(?:\w+)?\n(.*?)\n```", content, re.DOTALL)
                if code_match:
                    return "SUCCESS", code_match.group(1).strip()
                return "SUCCESS", content.strip("`").strip()

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
