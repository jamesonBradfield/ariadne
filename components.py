import json
import os
import subprocess
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError

import tree_sitter

from core import EngineContext, State


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
        print(f"[SENSOR] Query string: {query_string}")
        with open(filepath, "rb") as f:
            source_code = f.read()

        print(f"[SENSOR] Source code length: {len(source_code)} bytes")
        tree = self.parser.parse(source_code)
        query = tree_sitter.Query(self.language, query_string)

        query_cursor = tree_sitter.QueryCursor(query)
        captures = query_cursor.captures(tree.root_node)

        print(f"[SENSOR] Captures found: {captures}")

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
        """
        Validate that a string is valid Rust code by attempting to parse it.

        Args:
            code_string: The Rust code string to validate

        Returns:
            Dictionary with keys: valid (bool), error_message (str or None)
        """
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
        try:
            new_payload_bytes = new_payload.encode("utf8")

            before = full_source[:start_byte]
            after = full_source[end_byte:]

            new_source_code = before + new_payload_bytes + after

            with open(filepath, "wb") as f:
                f.write(new_source_code)

            return True
        except Exception as e:
            print(f"Drive-by-Wire failure: {e}")
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


class LLMProvider:
    """A lightweight, zero-dependency wrapper for llama.cpp server."""

    def __init__(self, base_url="http://localhost:8080/v1", verbose: bool = False):
        self.base_url = base_url
        self.verbose = verbose

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2048,
        stop_sequences: list = None,
        disable_thinking: bool = False,
    ) -> str:
        import time

        start_time = time.time()

        data = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,  # Keep it highly deterministic
            "max_tokens": max_tokens,
            "stream": False,
        }

        if disable_thinking:
            data["think"] = False

        if stop_sequences:
            data["stop"] = stop_sequences

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        try:
            if self.verbose:
                print(f"[LLM] Sending request to {self.base_url}/chat/completions...")
                print(f"[LLM] === FULL SYSTEM PROMPT ({len(system_prompt)} chars) ===")
                print(system_prompt)
                print(f"[LLM] === END SYSTEM PROMPT ===")
                print(f"[LLM] === FULL USER PROMPT ({len(user_prompt)} chars) ===")
                print(user_prompt)
                print(f"[LLM] === END USER PROMPT ===")
                print(
                    f"[LLM] max_tokens={max_tokens}, stop={stop_sequences}, disable_thinking={disable_thinking}"
                )
            req_start = time.time()
            with urllib.request.urlopen(req, timeout=60) as response:
                req_end = time.time()
                if self.verbose:
                    print(f"[LLM] Request took {req_end - req_start:.2f} seconds")

                result = json.loads(response.read().decode("utf-8"))
                raw_code = result["choices"][0]["message"]["content"].strip()

                if self.verbose:
                    print(f"[LLM] === RAW RESPONSE ({len(raw_code)} chars) ===")
                    print(raw_code)
                    print(f"[LLM] === END RAW RESPONSE ===")

                # Strip thinking tags from Qwen3 responses (including partial tags when stopped mid-generation)
                import re

                raw_code = re.sub(
                    r"<think>.*?</think>", "", raw_code, flags=re.DOTALL
                ).strip()
                raw_code = re.sub(
                    r"<think>.*", "", raw_code
                ).strip()  # Strip partial opening tags
                raw_code = raw_code.strip()  # Clean up any leftover whitespace

                # Safety Net: Strip markdown blocks if the model hallucinates them
                if raw_code.startswith("```"):
                    raw_code = "\n".join(raw_code.split("\n")[1:])
                if raw_code.endswith("```"):
                    raw_code = "\n".join(raw_code.split("\n")[:-1])

                end_time = time.time()
                if self.verbose:
                    print(
                        f"[LLM] Total generation took {end_time - start_time:.2f} seconds"
                    )
                return raw_code.strip()

        except URLError as e:
            end_time = time.time()
            if self.verbose:
                print(
                    f"[LLM] Connection Error after {end_time - start_time:.2f} seconds: {e}"
                )
            return None
        except Exception as e:
            end_time = time.time()
            if self.verbose:
                print(
                    f"[LLM] Unexpected Error after {end_time - start_time:.2f} seconds: {e}"
                )
            return None


class CodingState(State):
    def __init__(self, verbose: bool = True):
        super().__init__(name="CODING")
        self.llm = LLMProvider(base_url="http://localhost:8080/v1", verbose=verbose)

    def execute(self, context: EngineContext) -> str:
        target_data = context.data.get("extracted_node")
        intent = context.data.get("user_intent")
        language = context.data.get("language")

        if not target_data or not intent:
            context.data["errors"].append("Missing target data or intent for CODING.")
            return "IDLE"

        sys_prompt, usr_prompt = ECUPromptCompiler.compile(
            language, target_data["node_string"], intent
        )

        print(f"[{self.name}] Firing ECU (Local LLM at 8080)...")
        response = self.llm.generate(sys_prompt, usr_prompt)

        if not response:
            context.data["errors"].append("LLM generation failed or timed out.")
            return "IDLE"

        print(f"[{self.name}] Neural payload received ({len(response)} bytes).")
        context.data["llm_payload"] = response

        return "SYNTAX_GATE"


class SearchState(State):
    """
    Determines if the implementation already exists or where to edit.
    """

    def __init__(self, verbose: bool = True):
        super().__init__(name="SEARCH")
        self.llm = LLMProvider(base_url="http://localhost:8080/v1", verbose=verbose)

    def execute(self, context: EngineContext) -> str:
        filepath = context.data.get("filepath")
        intent = context.data.get("user_intent")
        language = context.data.get("language")

        if not filepath or not intent:
            context.data["errors"].append("Missing filepath or intent for SEARCH.")
            return "IDLE"

        # Read the entire file content
        try:
            with open(filepath, "rb") as f:
                source_code = f.read().decode("utf8")
        except Exception as e:
            context.data["errors"].append(f"Failed to read file {filepath}: {e}")
            return "IDLE"

        # If the file is empty, we definitely need to implement
        if not source_code.strip():
            context.data["target_name"] = ""  # Will need to be handled differently
            return "SENSE"

        system_prompt = (
            f"You are an expert {language} developer. DO NOT use <think> tags. "
            f"Your task is to determine if the user's intent "
            f"is already satisfied by the provided code. If the implementation already exists and fully "
            f"meets the intent, respond with the exact string 'EXISTS' (no quotes). "
            f"If the implementation does not exist or is incomplete, respond with the name of the function "
            f"or item that needs to be created or modified to fulfill the intent. "
            f"Respond with ONLY that string, no extra text, no markdown, no explanation."
        )
        user_prompt = (
            f"User Intent:\n{intent}\n\n"
            f"Full File Content ({filepath}):\n{source_code}\n\n"
            f"Does the implementation already exist? If yes, output EXISTS. If no, output the name of the function/item to edit/create."
        )

        print(f"[{self.name}] Querying LLM to check if implementation exists...")
        # Use disable_thinking to prevent rambling
        response = self.llm.generate(
            system_prompt, user_prompt, max_tokens=300, disable_thinking=True
        )

        if not response:
            context.data["errors"].append("LLM generation failed in SEARCH state.")
            return "IDLE"

        response = response.strip()
        print(f"[{self.name}] LLM raw response: '{response}'")

        if response.upper() == "EXISTS":
            print(
                f"[{self.name}] Implementation already exists. Skipping coding phase."
            )
            context.data["skip_coding"] = True
            return "IDLE"
        else:
            # Parse the function name from the response
            import re

            target_name = response
            # Try to extract just the function name
            fn_match = re.search(r"fn\s+(\w+)", target_name)
            if fn_match:
                target_name = fn_match.group(1)
            else:
                # Basic sanitization: take first line, strip whitespace
                target_name = target_name.split("\n")[0].strip()

            if not target_name:
                context.data["errors"].append("LLM did not return a valid target name.")
                return "IDLE"
            context.data["target_name"] = target_name
            # Construct a default Tree-sitter query for a function item with this name.
            # This assumes the target is a function; we could make this more dynamic later.
            context.data["target_func"] = (
                f'(function_item name: (identifier) @func_name (#eq? @func_name "{target_name}")) @function'
            )
            print(f"[{self.name}] Target set to '{target_name}'. Proceeding to SENSE.")
            return "SENSE"
