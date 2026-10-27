import json
import logging
import os
import subprocess
import asyncio
from typing import Any, Dict, List, Optional, Tuple

import tree_sitter
try:
    from ast_grep_py import SgRoot
except ImportError:
    SgRoot = None

from .core import State

logger = logging.getLogger("ariadne.primitives")


class QueryAstGrep(State):
    """
    Primitive for pattern-based AST searching using ast-grep.
    Input Payload: Dict with 'filepath' and 'pattern' (or 'rule').
    Returns: Tuple[str, List[Dict[str, Any]]] (status, matches)
    """

    def __init__(self, language: str):
        super().__init__("QUERY_AST_GREP")
        self.language = language

    def tick(
        self, payload: Dict[str, Any], context: "EngineContext"
    ) -> Tuple[str, List[Dict[str, Any]]]:
        filepath = payload.get("filepath")
        pattern = payload.get("pattern")
        rule = payload.get("rule")

        if not filepath or (not pattern and not rule):
            logger.warning(f"QueryAstGrep skipped: Missing parameters in {payload}")
            return "ERROR", []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()

            root = SgRoot(source, self.language)

            matches = []
            if rule:
                # Rule-based search (more complex)
                found = root.root().find_all(rule=rule)
            else:
                # Simple pattern search
                found = root.root().find_all(pattern=pattern)

            requested_vars = payload.get("vars", [])

            for node in found:
                range_info = node.range()
                match_data = {
                    "text": node.text(),
                    "start_byte": range_info.start.index,
                    "end_byte": range_info.end.index,
                    "start_line": range_info.start.line,
                    "start_col": range_info.start.column,
                    "node_type": node.kind(),
                }

                if requested_vars:
                    vars_data = {}
                    for v in requested_vars:
                        # ast-grep meta-vars in patterns are like $NAME, but get_match takes "NAME"
                        var_key = v.lstrip("$")
                        matched_node = node.get_match(var_key)
                        if matched_node:
                            vars_data[v] = matched_node.text()
                    match_data["vars"] = vars_data

                matches.append(match_data)

            return "SUCCESS", matches
        except Exception as e:
            logger.error(f"QueryAstGrep Error: {e}")
            return "ERROR", [{"error": str(e)}]


class QueryMCP(State):
    """
    Agnostic MCP query primitive.
    Connects to an MCP server via stdio and calls a tool.
    Input Payload: Dict with 'command', 'args', 'tool_name', and 'tool_args'.
    Returns: Tuple[str, Any] (status, result)
    """

    def __init__(self):
        super().__init__("QUERY_MCP")

    async def _query(
        self, command: str, args: List[str], tool_name: str, tool_args: Dict[str, Any]
    ) -> Any:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(command=command, args=args, env=None)

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call the tool
                result = await session.call_tool(tool_name, tool_args)
                return result

    def tick(
        self, payload: Dict[str, Any], context: "EngineContext"
    ) -> Tuple[str, Any]:
        command = payload.get("command")
        args = payload.get("args", [])
        tool_name = payload.get("tool_name")
        tool_args = payload.get("tool_args", {})

        if not command or not tool_name:
            logger.warning(
                f"QueryMCP skipped: Missing command ({command}) or tool_name ({tool_name})"
            )
            return "ERROR", "Missing parameters"

        try:
            # Run the async query in a synchronous way for the HFSM
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                self._query(command, args, tool_name, tool_args)
            )
            loop.close()

            return "SUCCESS", result
        except Exception as e:
            logger.error(f"QueryMCP Error: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return "ERROR", str(e)


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

    def tick(
        self, payload: Dict[str, Any], context: "EngineContext"
    ) -> Tuple[str, List[str]]:
        filepath = payload.get("filepath")
        query_string = payload.get("query_string")
        capture_name = payload.get("capture_name", "node")

        if not filepath or not query_string:
            logger.warning(
                f"ExtractAST skipped: Missing filepath ({filepath}) or query_string ({query_string})"
            )
            return "ERROR", []

        try:
            with open(filepath, "rb") as f:
                source_code = f.read()

            tree = self.parser.parse(source_code)
            # Create a Query object from the query_string
            query = tree_sitter.Query(self.language, query_string.encode("utf-8"))
            query_cursor = tree_sitter.QueryCursor(query)

            results = []  # Initialize results list
            captures = query_cursor.captures(tree.root_node)

            # Normalize captures to List[Tuple[Node, str]]
            normalized_captures = []
            if isinstance(captures, dict):
                # Tree-sitter 0.25.2: Dict[str, List[Node]]
                for name, nodes in captures.items():
                    for node in nodes:
                        normalized_captures.append((node, name))
            else:
                # Older/standard versions: List[Tuple[Node, str, index]] or List[Tuple[Node, str]]
                for item in captures:
                    if isinstance(item, tuple) and len(item) >= 2:
                        normalized_captures.append((item[0], item[1]))

            # Process normalized captures
            for node, name in normalized_captures:
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

    def tick(
        self, payload: Dict[str, Any], context: "EngineContext"
    ) -> Tuple[str, Any]:
        import litellm
        import re
        import tiktoken

        system = payload.get("system", "")
        user = payload.get("user", "")
        params = payload.get("params", {})
        response_model = payload.get("response_model")

        # Empirical Token Measurement
        try:
            encoding = tiktoken.get_encoding("cl100k_base")  # Standard for GPT-4/Turbo
            input_tokens = len(encoding.encode(system + user))
        except Exception:
            input_tokens = 0

        logger.info(f"[LLM REQUEST] System Prompt: {system}")
        logger.info(f"[LLM REQUEST] User Prompt: {user}")
        logger.info(f"[TOKEN BUDGET] Input: ~{input_tokens} tokens")

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
                "stream": True,  # Always stream for UX polish
            }
            completion_args.update(params)

            if self.api_key:
                completion_args["api_key"] = self.api_key

            # Use native structured output if response_model is provided
            if response_model:
                completion_args["response_format"] = response_model
                # Structured output + streaming usually requires buffering

            content = ""
            reasoning = ""

            # Identify role for UI
            role_label = "Ariadne"
            if "Architect" in system:
                role_label = "Architect"
            elif "Surgeon" in system:
                role_label = "Surgeon"
            elif "Router" in system:
                role_label = "Router"

            response_gen = litellm.completion(**completion_args)

            for chunk in response_gen:
                # Check for context abort (Stop button or turns limit)
                if context.stop_requested:
                    logger.warning("Stop requested during LLM stream. Terminating.")
                    return "ABORT", "Interrupted by user."

                delta = chunk.choices[0].delta

                # Handle standard content
                chunk_content = getattr(delta, "content", None)
                if chunk_content:
                    content += chunk_content

                # Handle reasoning content
                chunk_reasoning = getattr(delta, "reasoning_content", None)
                if not chunk_reasoning and hasattr(delta, "provider_specific_fields"):
                    psf = delta.provider_specific_fields or {}
                    chunk_reasoning = psf.get("reasoning_content")

                if chunk_reasoning:
                    reasoning += chunk_reasoning

                # Emit streaming event for UI
                context.emit(
                    "LLM_STREAM",
                    {"role": role_label, "content": content, "reasoning": reasoning},
                )

            # Post-stream processing
            if reasoning:
                logger.info(f"[LLM REASONING]\n{reasoning}")
                # Salvage logic: If main content is empty but reasoning contains the answer
                if not content.strip():
                    logger.warning(
                        "Main content empty. Attempting to salvage from reasoning_content..."
                    )
                    json_patterns = [
                        r"(\{\s*\"reasoning\":.*?\})",
                        r"(\{\s*\"action\":.*?\})",
                        r"(\{\s*\"steps\":.*?\})",
                        r"(\{.*\})",  # Fallback
                    ]

                    found_json = False
                    valid_states = [
                        "DISPATCH",
                        "MAPS_NAV",
                        "THINKING",
                        "ABORT",
                        "SUCCESS",
                        "MAPS_THINK",
                        "MAPS_SURGEON",
                        "SYNTAX_GATE",
                        "ACTUATE",
                        "INTERVENE",
                        "FILE_EXPLORER",
                        "SPAWN",
                        "EVALUATE",
                        "POST_MORTEM",
                    ]

                    for pattern in json_patterns:
                        matches = re.finditer(pattern, reasoning, re.DOTALL)
                        for match in matches:
                            candidate = match.group(1)
                            if (
                                '"..."' in candidate
                                or "<string>" in candidate
                                or "<next_state>" in candidate
                            ):
                                continue
                            if "next_state" in candidate:
                                if not any(f'"{s}"' in candidate for s in valid_states):
                                    continue
                            if "steps" in candidate and "[]" in candidate:
                                continue
                            content = candidate
                            found_json = True
                            break
                        if found_json:
                            break

                    if not found_json:
                        code_match = re.search(
                            r"```(?:\w+)?\n(.*?)\n```", reasoning, re.DOTALL
                        )
                        if code_match:
                            content = code_match.group(1)
                        else:
                            paragraphs = [
                                p.strip() for p in reasoning.split("\n\n") if p.strip()
                            ]
                            meta_markers = [
                                "self-correction",
                                "thinking process",
                                "note:",
                                "prompt asks",
                                "analyzing",
                                "identifying",
                                "identifying key",
                                "draft the intent",
                                "refine for conciseness",
                                "constraint:",
                                "task:",
                            ]
                            best_candidate = ""
                            for p in reversed(paragraphs):
                                p_lower = p.lower()
                                if any(m in p_lower for m in meta_markers):
                                    continue
                                if len(p) > 400 and p.count("*") > 2:
                                    continue
                                best_candidate = p
                                break
                            if best_candidate:
                                content = best_candidate
                                clean_headers = [
                                    "final output generation:",
                                    "final output:",
                                    "objective:",
                                    "summary:",
                                    "technical intent:",
                                ]
                                for ch in clean_headers:
                                    if content.lower().startswith(ch):
                                        content = content[len(ch) :].strip()
                                        break
                            elif paragraphs:
                                content = paragraphs[-1]

            # Measure Output Tokens
            try:
                output_tokens = len(encoding.encode(content))
            except Exception:
                output_tokens = 0

            context.total_tokens += input_tokens + output_tokens
            logger.info(
                f"[TOKEN BUDGET] Output: ~{output_tokens} tokens | Session Total: ~{context.total_tokens}"
            )

            if response_model:
                try:
                    import json

                    json_str = content
                    if "{" in content:
                        json_str = content[content.find("{") : content.rfind("}") + 1]
                    parsed = response_model.model_validate_json(json_str)
                    return "SUCCESS", parsed
                except Exception as e:
                    logger.error(f"Failed to validate JSON against model: {e}")
                    return "JSON_ERROR", content

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

    def tick(self, command: str, context: "EngineContext") -> Tuple[str, str]:
        try:
            # shell=True for terminal-like behavior, timeout to prevent hanging
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=120
            )
            output = f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

            # Emit stdout event for UI
            context.emit("STDOUT", {"text": output})

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

    def tick(self, proposal: str, context: "EngineContext") -> Tuple[str, bool]:
        import os

        if os.getenv("ARIADNE_AUTO_ACCEPT") == "true":
            logger.info("Auto-accepting proposal due to ARIADNE_AUTO_ACCEPT=true")
            return "ACCEPTED", True

        # Emit event for UI to handle
        context.emit("USER_PROMPT", {"proposal": proposal})

        # This blocks the engine thread until UI calls context.submit_user_response()
        response = context.wait_for_user()

        if response is None:
            return "REJECTED", False

        approved = (
            response.get("approved", False)
            if isinstance(response, dict)
            else bool(response)
        )
        return "ACCEPTED" if approved else "REJECTED", approved


class WriteFile(State):
    """
    Agnostic file writing primitive.
    Input Payload: Dict with 'filepath' and 'content'.
    Returns: Tuple[str, str] (status, filepath)
    """

    def __init__(self):
        super().__init__("WRITE_FILE")

    def tick(
        self, payload: Dict[str, str], context: "EngineContext"
    ) -> Tuple[str, str]:
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

    def tick(
        self, payload: Dict[str, Any], context: "EngineContext"
    ) -> Tuple[str, str]:
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
                    logger.error(
                        "ASTSplice rejected: Code contains markdown backticks."
                    )
                    return "REJECTED", "Markdown detected"

                new_code_bytes = new_code.encode("utf-8")
                start_byte = edit["start_byte"]
                end_byte = edit["end_byte"]

                before = new_source_code[:start_byte]
                after = new_source_code[end_byte:]
                new_source_code = before + new_code_bytes + after

            logger.info(f"Writing {len(new_source_code)} bytes to {filepath}")
            with open(filepath, "wb") as f:
                f.write(new_source_code)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass

            return "SUCCESS", filepath
        except Exception as e:
            logger.error(f"ASTSplice Error: {e}")
            return "ERROR", str(e)


class BlockSplice(State):
    """
    Surgical AST block splicing primitive.
    Input Payload: Dict with 'filepath' and 'edits' (list of dicts with 'start_byte', 'end_byte', 'new_code').
    Returns: Tuple[str, str] (status, filepath)
    """

    def __init__(self):
        super().__init__("BLOCK_SPLICE")

    def tick(
        self, payload: Dict[str, Any], context: "EngineContext"
    ) -> Tuple[str, str]:
        filepath = payload.get("filepath")
        edits = payload.get("edits", [])

        if not edits:
            return "SUCCESS", filepath

        # Sort edits in reverse order (bottom-up) to prevent byte offset corruption
        edits.sort(key=lambda x: x["start_byte"], reverse=True)

        try:
            with open(filepath, "rb") as f:
                new_source_code = f.read()

            for edit in edits:
                start_byte = edit["start_byte"]
                end_byte = edit["end_byte"]

                if "new_code" in edit:
                    # Direct replacement protocol
                    new_node_text = edit["new_code"].replace("\r\n", "\n")
                    # Restore CRLF if the file uses it
                    if b"\r\n" in new_source_code[start_byte:end_byte]:
                        new_node_text = new_node_text.replace("\n", "\r\n")
                    new_node_bytes = new_node_text.encode("utf-8")
                else:
                    # Legacy SEARCH/REPLACE protocol
                    search_text = edit["search_text"]
                    replace_text = edit["replace_text"]

                    node_bytes = new_source_code[start_byte:end_byte]
                    node_text = node_bytes.decode("utf-8")

                    search_norm = search_text.replace("\r\n", "\n")
                    node_norm = node_text.replace("\r\n", "\n")

                    if search_norm not in node_norm:
                        logger.error(
                            f"BlockSplice rejected: search_text not found in target node."
                        )
                        return "REJECTED", "search_text not found in node"

                    replace_norm = replace_text.replace("\r\n", "\n")
                    new_node_text_norm = node_norm.replace(search_norm, replace_norm, 1)

                    if b"\r\n" in node_bytes:
                        new_node_text = new_node_text_norm.replace("\n", "\r\n")
                    else:
                        new_node_text = new_node_text_norm
                    new_node_bytes = new_node_text.encode("utf-8")

                before = new_source_code[:start_byte]
                after = new_source_code[end_byte:]
                new_source_code = before + new_node_bytes + after

            logger.info(f"Writing {len(new_source_code)} bytes to {filepath}")
            dir_name = os.path.dirname(os.path.abspath(filepath))
            tmp_path = os.path.join(dir_name, f".{os.path.basename(filepath)}.tmp.{os.getpid()}")
            with open(tmp_path, "wb") as f:
                f.write(new_source_code)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            os.replace(tmp_path, filepath)

            return "SUCCESS", filepath
        except Exception as e:
            logger.error(f"BlockSplice Error: {e}")
            return "ERROR", str(e)


class QueryClef(State):
    """Clef-flash aperture primitive: fast prefill/decision pass returning calibrated probabilities."""

    def __init__(self, model: Optional[str] = None, api_base: Optional[str] = None, api_key: Optional[str] = None):
        super().__init__("QUERY_CLEF")
        import os
        self.api_base = api_base or os.getenv("CLEF_API_BASE") or os.getenv("CLOUDFLARE_CLEF_URL") or "http://localhost:8080/v1"
        default_model = "clef-flash" if "cloudflare" in self.api_base else "Spark-RTN"
        self.model = model or os.getenv("CLEF_MODEL") or default_model
        self.api_key = api_key or os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CLEF_API_KEY") or "none"

    def deterministic_classify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Endpoint-free decision pass used when no api_base is configured.
        Returns the SAME intermediate result shape the model calls produce, so
        tick()'s per-mode post-processing consumes it unchanged. Deliberately
        conservative: default is in_progress / continue_splice / mid-range
        turn estimate; keyword signals in the state nudge toward done/stuck."""
        import json
        mode = payload.get("mode", "aperture")
        state = payload.get("state")
        low = (state if isinstance(state, str) else json.dumps(state or "")).lower()
        done = any(k in low for k in ("completed", "task done", "success", "all tests pass"))
        stuck = any(k in low for k in ("error", "failed", "stuck", "blocked", "cannot proceed"))
        if mode == "verify_objective":
            return {
                "objective_status": {
                    "completed": 0.9 if done else 0.05,
                    "in_progress": 0.9 if not (done or stuck) else 0.05,
                    "blocked_or_stuck": 0.9 if (stuck and not done) else 0.05,
                },
                "recommended_action": {
                    "continue_splice": 0.9 if not (done or stuck) else 0.05,
                    "kanban_complete": 0.9 if done else 0.05,
                    "escalate_to_planner": 0.9 if (stuck and not done) else 0.05,
                },
                "remaining_turns_bucket": {
                    "0": 0.9 if done else 0.02,
                    "1-5": 0.03,
                    "6-15": 0.9 if not done else 0.01,
                    "15+": 0.07,
                },
            }
        if mode == "estimate_turns":
            return {
                "remaining_turns_bucket": {"1-5": 0.03, "6-15": 0.9, "15-30": 0.05, "30+": 0.02},
                "task_complexity": {"low": 0.05, "medium": 0.9, "high": 0.05},
            }
        # Legacy aperture shape
        return {
            "isolated_node_sufficient": False,
            "surgical_action": "replace",
            "confidence": 0.5,
            "needed_slices": ["parent_skeleton", "file_imports", "call_sites"],
        }

    def tick(self, payload: Dict[str, Any], context: "EngineContext" = None) -> Tuple[str, Any]:
        import json
        import urllib.request
        import urllib.error

        # NOTE: the no-endpoint fallback is NOT an early ERROR return here — it
        # runs deterministic_classify in the request branch below so the normal
        # per-mode post-processing still consumes the heuristic decisions.

        mode = payload.get("mode", "aperture")
        state = payload.get("state")
        questions = payload.get("questions")

        if not questions:
            if mode == "verify_objective":
                questions = {
                    "objective_status": {
                        "type": "choice",
                        "options": ["in_progress", "completed", "blocked_or_stuck"]
                    },
                    "recommended_action": {
                        "type": "choice",
                        "options": ["continue_splice", "kanban_complete", "escalate_to_planner"]
                    },
                    "remaining_turns_bucket": {
                        "type": "choice",
                        "options": ["0", "1-5", "6-15", "15+"]
                    }
                }
            elif mode == "estimate_turns":
                questions = {
                    "remaining_turns_bucket": {
                        "type": "choice",
                        "options": ["1-5", "6-15", "15-30", "30+"]
                    },
                    "task_complexity": {
                        "type": "choice",
                        "options": ["low", "medium", "high"]
                    }
                }
            else:
                questions = payload.get("questions", {})

        # If pointing to local OpenAI-compatible endpoint (e.g. llama-swap port 8080)
        is_openai_compat = ("8080" in self.api_base or "chat/completions" in self.api_base) and not ("8093" in self.api_base or "clef" in self.api_base.lower())
        if not self.api_base:
            # Heuristic decision pass — same shape the model branches produce.
            result = self.deterministic_classify(payload)
        elif is_openai_compat:
            endpoint = self.api_base.rstrip("/")
            if not endpoint.endswith("/chat/completions"):
                endpoint = f"{endpoint}/chat/completions"

            state_str = state if isinstance(state, str) else json.dumps(state, indent=2)
            if mode == "verify_objective":
                sys_msg = (
                    "You are a task verifier. Output ONLY JSON with choice probabilities:\n"
                    "{\n"
                    '  "objective_status": {"in_progress": float, "completed": float, "blocked_or_stuck": float},\n'
                    '  "recommended_action": {"continue_splice": float, "kanban_complete": float, "escalate_to_planner": float},\n'
                    '  "remaining_turns_bucket": {"0": float, "1-5": float, "6-15": float, "15+": float}\n'
                    "}"
                )
            elif mode == "estimate_turns":
                sys_msg = (
                    "You are a task complexity estimator. Output ONLY JSON:\n"
                    "{\n"
                    '  "remaining_turns_bucket": {"1-5": float, "6-15": float, "15-30": float, "30+": float},\n'
                    '  "task_complexity": {"low": float, "medium": float, "high": float}\n'
                    "}"
                )
            else:
                sys_msg = (
                    "You are an AST surgical repair classifier. Output ONLY a JSON object:\n"
                    "{\n"
                    '  "isolated_node_sufficient": true | false,\n'
                    '  "surgical_action": "replace" | "insert_before" | "insert_after" | "delete",\n'
                    '  "confidence": float,\n'
                    '  "needed_slices": ["parent_skeleton", "file_imports", "lsp_hover", "call_sites", "test_contract_assertions", "last_attempted_diff"]\n'
                    "}"
                )

            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": state_str}
                ],
                "max_tokens": 120,
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                if self.api_key and self.api_key != "none":
                    req.add_header("Authorization", f"Bearer {self.api_key}")

                with urllib.request.urlopen(req, timeout=10) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    raw = res["choices"][0]["message"]["content"]
                    result = json.loads(raw)
            except Exception as e:
                return "ERROR", {"error": str(e)}
        else:
            # Native Cloudflare Workers AI / Clef NAR format
            body = {"state": state, "questions": questions}
            try:
                req = urllib.request.Request(
                    self.api_base,
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                if self.api_key and self.api_key != "none":
                    req.add_header("Authorization", f"Bearer {self.api_key}")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                result = data.get("result", data.get("decisions", data))
            except Exception as e:
                return "ERROR", {"error": str(e)}

        if mode == "verify_objective":
            obj_probs = result.get("objective_status", {})
            action_probs = result.get("recommended_action", {})
            remaining_probs = result.get("remaining_turns_bucket", {})

            completed_prob = float(obj_probs.get("completed", 0.0))
            stuck_prob = float(obj_probs.get("blocked_or_stuck", 0.0))
            complete_action_prob = float(action_probs.get("kanban_complete", 0.0))
            escalate_prob = float(action_probs.get("escalate_to_planner", 0.0))

            is_completed = (completed_prob >= 0.80 or complete_action_prob >= 0.80)
            is_stuck = (stuck_prob >= 0.75 or escalate_prob >= 0.75)
            rec_action = max(action_probs, key=action_probs.get) if action_probs else ("kanban_complete" if is_completed else "continue_splice")
            est_rem = max(remaining_probs, key=remaining_probs.get) if remaining_probs else "0"

            return "SUCCESS", {
                "objective_satisfied": is_completed,
                "completion_confidence": max(completed_prob, complete_action_prob),
                "is_stuck": is_stuck,
                "recommended_action": rec_action,
                "remaining_turns_bucket": est_rem,
                "raw_decisions": result
            }
        elif mode == "estimate_turns":
            rem_probs = result.get("remaining_turns_bucket", {})
            best_bucket = max(rem_probs, key=rem_probs.get) if rem_probs else "6-15"
            bucket_map = {"1-5": 5, "6-15": 15, "15-30": 25, "30+": 35}
            est = bucket_map.get(best_bucket, 15)
            return "SUCCESS", {
                "estimated_turns": est,
                "max_budget": est * 2,
                "bucket": best_bucket,
                "raw_decisions": result
            }

        # Legacy aperture decisions
        conf = float(result.get("confidence", 0.9)) if isinstance(result, dict) else 0.9
        is_suff = bool(result.get("isolated_node_sufficient", True)) if isinstance(result, dict) else True
        prob_suff = conf if is_suff else (1.0 - conf)
        action = result.get("surgical_action", "replace") if isinstance(result, dict) else "replace"
        needed = result.get("needed_slices", []) if isinstance(result, dict) else []

        decisions = {
            "isolated_node_sufficient": {"probability": prob_suff},
            "surgical_action": {"choice": action, "confidence": conf}
        }
        for key in questions:
            if key.startswith("need_"):
                slice_name = key[5:]
                decisions[key] = {"probability": 0.95 if slice_name in needed else 0.05}
        return "SUCCESS", decisions
