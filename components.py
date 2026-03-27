import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError

import litellm
import tree_sitter
from litellm.exceptions import ServiceUnavailableError

from core import State

logger = logging.getLogger("ariadne.components")


class TreeSitterSensor:
    """
    A language-agnostic sensor that queries an AST and extracts raw byte coordinates.
    """

    def __init__(self, language_ptr):
        # We pass the language in (e.g., tree_sitter_rust.language()) so this
        # component remains 100% universal.
        self.language = tree_sitter.Language(language_ptr)
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

        if capture_name in captures and captures[capture_name]:
            # Grab the very first match found
            target_node = captures[capture_name][0]

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
    A generic wrapper to run shell commands and capture stdout/stderr.
    """

    def __init__(self, command: list, timeout: int = 30):
        """
        Initialize the subprocess sensor.

        Args:
            command: List of command and arguments (e.g., ["cargo", "check"])
            timeout: Timeout in seconds
        """
        self.command = command
        self.timeout = timeout

    def execute(self) -> Dict[str, Any]:
        """
        Run the command and capture output.

        Returns:
            Dictionary with keys: success (bool), stdout (str), stderr (str), returncode (int)
        """
        try:
            result = subprocess.run(
                self.command, capture_output=True, text=True, timeout=self.timeout
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Command timed out after {self.timeout} seconds",
                "returncode": -1,
            }
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}


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


class DriveByWireActuator:
    """
    Surgically injects new bytes into a file based on exact start/end coordinates.
    """

    @staticmethod
    def splice(
        filepath: str,
        full_source: bytes,
        start_byte: int,
        end_byte: int,
        new_payload: str,
    ) -> bool:
        if "```" in new_payload:
            logger.error("Refusing to splice payload containing backticks (LLM leak).")
            return False

        try:
            new_payload_bytes = new_payload.encode("utf8")

            before = full_source[:start_byte]
            after = full_source[end_byte:]

            new_source_code = before + new_payload_bytes + after

            with open(filepath, "wb") as f:
                f.write(new_source_code)

            return True
        except Exception as e:
            logger.error(f"Drive-by-Wire failure: {e}")
            return False


class ECUPromptCompiler:
    """Compiles the raw AST node and user intent into a strict prompt."""

    @staticmethod
    def compile(language: str, target_code: str, intent: str) -> Tuple[str, str]:
        system_prompt = (
            f"You are an expert {language} developer. You act as an execution engine. "
            f"You only output raw, valid {language} code. NO markdown formatting. "
            f"NO backticks. NO conversational text or explanations."
        )
        user_prompt = (
            f"Rewrite this code to fulfill the following intent: {intent}\n\n"
            f"Code to rewrite:\n{target_code}"
        )
        return system_prompt, user_prompt


class LiteLLMProvider:
    """
    A lightweight wrapper for litellm, allowing connection to any LLM backend.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        verbose: bool = False,
    ):
        # 1. Prioritize passed args, then Env, then local defaults
        self.base_url = (
            base_url or os.getenv("ARIADNE_API_BASE") or "http://localhost:8080/v1"
        )

        default_model = (
            "openai/llama-cpp" if "localhost" in self.base_url else "ollama/llama3"
        )
        self.model = model or os.getenv("ARIADNE_MODEL") or default_model

        self.verbose = verbose
        if self.verbose:
            logger.info(
                f"[LLM] Initialized with Model: {self.model}, Base: {self.base_url}"
            )

        self.api_key = os.getenv("ARIADNE_API_KEY") or "none"

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2048,
        stop_sequences: list = None,
        stream: bool = False,
        stop_at_newline: bool = False,
        max_retries: int = 5,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.debug(f"[LLM REQUEST] System: {system_prompt}")
        logger.debug(f"[LLM REQUEST] User: {user_prompt}")

        for attempt in range(max_retries):
            try:
                if self.verbose:
                    logger.info(
                        f"[LLM] Sending request to {self.model} (stream={stream}, attempt={attempt + 1})..."
                    )

                if stream:
                    response_iter = litellm.completion(
                        model=self.model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=0.1,
                        api_base=self.base_url,
                        api_key=self.api_key,
                        stop=stop_sequences,
                        stream=True,
                    )

                    full_content = ""
                    for chunk in response_iter:
                        content = chunk.choices[0].delta.content
                        if content:
                            full_content += content
                            if stop_at_newline and (
                                "\n" in full_content
                                or len(full_content.strip().split()) > 5
                            ):
                                break
                    logger.debug(f"[LLM RESPONSE] Raw (Streamed): {full_content}")
                    return full_content.strip()
                else:
                    response = litellm.completion(
                        model=self.model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=0.1,
                        api_base=self.base_url,
                        api_key=self.api_key,
                        stop=stop_sequences,
                    )
                    raw_content = response.choices[0].message.content
                    logger.debug(f"[LLM RESPONSE] Raw: {raw_content}")
                    return raw_content.strip()

            except ServiceUnavailableError as e:
                if "Loading model" in str(e) and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5
                    logger.warning(
                        f"[LLM] Server is still loading model. Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    continue
                raise e
            except Exception as e:
                if self.verbose:
                    logger.error(f"[LLM] Error: {e}")
                return None
        return None


class CodingState(State):
    def __init__(self, verbose: bool = True):
        super().__init__(name="CODING")
        self.llm = LiteLLMProvider(verbose=verbose)

    def tick(self, payload: Any) -> Tuple[str, Any]:
        # Placeholder: Logic to be implemented in Phase 2
        logger.info(f"[{self.name}] Firing ECU...")
        return "SYNTAX_GATE", payload


class Skeletonizer:
    """
    A pure Python skeletonizer that uses tree-sitter to strip function bodies.
    """

    @staticmethod
    def skeletonize(filepath: str, profile: Any) -> Optional[str]:
        try:
            with open(filepath, "rb") as f:
                source_code = f.read()

            language = tree_sitter.Language(profile.get_language_ptr())
            parser = tree_sitter.Parser(language)
            tree = parser.parse(source_code)

            query = tree_sitter.Query(language, profile.get_skeleton_query())
            query_cursor = tree_sitter.QueryCursor(query)
            captures = query_cursor.captures(tree.root_node)

            # We want to replace the 'body' capture of each function
            body_spans = []
            if "body" in captures:
                for node in captures["body"]:
                    body_spans.append((node.start_byte, node.end_byte))

            if not body_spans:
                return source_code.decode("utf8")

            # Sort spans in reverse order to replace without shifting offsets
            body_spans.sort(key=lambda x: x[0], reverse=True)

            result = bytearray(source_code)
            for start, end in body_spans:
                result[start:end] = b"{ ... }"

            return result.decode("utf8")
        except Exception as e:
            logger.error(f"[SKELETONIZER] Python skeletonization failed: {e}")
            return None


class SearchState(State):
    """
    Determines if the implementation already exists or where to edit.
    """

    def __init__(self, verbose: bool = True):
        super().__init__(name="SEARCH")
        self.llm = LiteLLMProvider(verbose=verbose)

    def tick(self, payload: Any) -> Tuple[str, Any]:
        # Placeholder: Logic to be implemented in Phase 2
        logger.info(f"[{self.name}] Querying LLM with skeletonized context...")
        return "SENSE", payload
