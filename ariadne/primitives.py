import json
import logging
import os
import subprocess
import asyncio
from typing import Any, Dict, List, Optional, Tuple

import tree_sitter
from ast_grep_py import SgRoot

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

    def tick(self, payload: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
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
                    "node_type": node.kind()
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

    async def _query(self, command: str, args: List[str], tool_name: str, tool_args: Dict[str, Any]) -> Any:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=None
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # Call the tool
                result = await session.call_tool(tool_name, tool_args)
                return result

    def tick(self, payload: Dict[str, Any]) -> Tuple[str, Any]:
        command = payload.get("command")
        args = payload.get("args", [])
        tool_name = payload.get("tool_name")
        tool_args = payload.get("tool_args", {})

        if not command or not tool_name:
            logger.warning(f"QueryMCP skipped: Missing command ({command}) or tool_name ({tool_name})")
            return "ERROR", "Missing parameters"

        try:
            # Run the async query in a synchronous way for the HFSM
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._query(command, args, tool_name, tool_args))
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

    def tick(self, payload: Dict[str, Any]) -> Tuple[str, Any]:
        import litellm
        import re

        system = payload.get("system", "")
        user = payload.get("user", "")
        params = payload.get("params", {})
        post_process = payload.get("post_process")
        response_model = payload.get("response_model")

        logger.info(f"[LLM REQUEST] System Prompt: {system}")
        logger.info(f"[LLM REQUEST] User Prompt: {user}")

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
            
            # Use native structured output if response_model is provided
            if response_model:
                completion_args["response_format"] = response_model
                # Ensure stop sequence is preserved even in structured mode
                if "stop" in params:
                    completion_args["stop"] = params["stop"]

            response = litellm.completion(**completion_args)
            
            # DEBUG: Print the raw response object
            print(f"\n[DEBUG LLM RESPONSE OBJ]\n{response.model_dump_json(indent=2)}\n")
            
            message = response.choices[0].message
            content = message.content or ""
            
            # Extract reasoning content (common in Qwen/DeepSeek/local reasoning models)
            reasoning = getattr(message, "reasoning_content", None)
            if not reasoning and hasattr(message, "provider_specific_fields"):
                psf = message.provider_specific_fields or {}
                reasoning = psf.get("reasoning_content")

            if reasoning:
                logger.info(f"[LLM REASONING]\n{reasoning}")
                # Salvage logic: If main content is empty but reasoning contains the answer, 
                # try to extract it (especially if we hit token limits)
                if not content.strip():
                    logger.warning("Main content empty. Attempting to salvage from reasoning_content...")
                    # Look for JSON first - prefer objects with common Ariadne keys
                    # This avoids grabbing Rust code blocks that happen to use braces
                    json_patterns = [
                        r"(\{\s*\"reasoning\":.*?\})",
                        r"(\{\s*\"action\":.*?\})",
                        r"(\{\s*\"steps\":.*?\})",
                        r"(\{.*\})" # Fallback
                    ]
                    
                    found_json = False
                    valid_states = ["SEARCH", "DISPATCH", "MAPS_NAV", "THINKING", "ABORT", "ROUTER", "SUCCESS", "SENSE", "MAPS_THINK", "MAPS_SURGEON", "SYNTAX_GATE", "ACTUATE", "INTERVENE"]
                    
                    for pattern in json_patterns:
                        matches = re.finditer(pattern, reasoning, re.DOTALL)
                        for match in matches:
                            candidate = match.group(1)
                            # Skip templates/placeholders
                            if '\"...\"' in candidate or '<string>' in candidate or '<next_state>' in candidate:
                                continue
                            
                            # NEW: Strict State/Symbol Check
                            # If it looks like a Router response, it MUST have a valid next_state
                            if "next_state" in candidate:
                                if not any(f'"{s}"' in candidate for s in valid_states):
                                    continue
                            
                            # If it's a Thinking plan, it MUST have at least one step
                            if "steps" in candidate and "[]" in candidate:
                                continue

                            content = candidate
                            found_json = True
                            break
                        if found_json: break
                    
                    if not found_json:
                        # Look for markdown code blocks
                        code_match = re.search(r"```(?:\w+)?\n(.*?)\n```", reasoning, re.DOTALL)
                        if code_match:
                            content = code_match.group(1)
                        else:
                            # Use the last paragraph if nothing else, but filter out meta-commentary
                            paragraphs = [p.strip() for p in reasoning.split("\n\n") if p.strip()]
                            meta_markers = ["self-correction", "thinking process", "note:", "prompt asks", "analyzing", "identifying", "identifying key", "draft the intent", "refine for conciseness", "constraint:", "task:"]
                            
                            # Try to find a paragraph that looks like a final statement (working backwards)
                            best_candidate = ""
                            for p in reversed(paragraphs):
                                # Skip if it looks like meta-commentary or starts with a common reasoning header
                                if any(p.lower().startswith(m) for m in meta_markers):
                                    continue
                                best_candidate = p
                                break
                            
                            if best_candidate:
                                content = best_candidate
                                # Strip common "header" prefixes from the candidate
                                clean_headers = ["final output generation:", "final output:", "objective:", "summary:", "technical intent:"]
                                for ch in clean_headers:
                                    if content.lower().startswith(ch):
                                        content = content[len(ch):].strip()
                                        break
                            elif paragraphs:
                                content = paragraphs[-1]

            if response_model:
                # litellm returns the parsed model object in message.content for supported providers
                # or we can access it via response.choices[0].message.content if it's just a string
                if hasattr(content, "model_dump"): # It's a Pydantic object
                    logger.info(f"[LLM RESPONSE] Structured Data: {content.model_dump_json()}")
                    return "SUCCESS", content
                else:
                    # It might be a JSON string that litellm didn't auto-parse (common with some providers)
                    logger.info(f"[LLM RESPONSE] Raw Content (Expected JSON): {content}")
                    try:
                        import json
                        # Clean potential chatter around JSON if salvaged
                        json_str = content
                        if "{" in content:
                            json_str = content[content.find("{"):content.rfind("}")+1]
                        parsed = response_model.model_validate_json(json_str)
                        return "SUCCESS", parsed
                    except Exception as e:
                        logger.error(f"Failed to validate JSON against model: {e}")
                        return "JSON_ERROR", content

            logger.info(f"[LLM RESPONSE] Raw Content: {content}")

            # Legacy Post-Processing Logic (Strip Markdown etc.)
            if post_process == "strip_markdown":
                cleaned_content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                cleaned_content = re.sub(r"</?think>", "", cleaned_content, flags=re.IGNORECASE).strip()
                
                code_match = re.search(r"```(?:\w+)?\n(.*?)\n```", cleaned_content, re.DOTALL)
                if code_match:
                    return "SUCCESS", code_match.group(1).strip()
                return "SUCCESS", cleaned_content.strip("`").strip()

            if post_process == "extract_search_replace":
                cleaned_content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                
                search_lines = []
                replace_lines = []
                state = "SCANNING"
                
                for line in cleaned_content.splitlines():
                    stripped = line.strip()
                    
                    if stripped.startswith("<<<< SEARCH"):
                        state = "IN_SEARCH"
                        continue
                    elif stripped.startswith("===="):
                        state = "IN_REPLACE"
                        continue
                    elif stripped.startswith(">>>> REPLACE"):
                        continue
                    elif stripped.startswith(">>>>"):
                        break
                        
                    if state == "IN_SEARCH":
                        search_lines.append(line)
                    elif state == "IN_REPLACE":
                        replace_lines.append(line)
                
                if search_lines or replace_lines:
                    line_ending = "\r\n" if "\r\n" in cleaned_content else "\n"
                    search_text = line_ending.join(search_lines)
                    replace_text = line_ending.join(replace_lines)
                    return "SUCCESS", {"search": search_text, "replace": replace_text}

                return "SEARCH_REPLACE_ERROR", content

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
        self.app = None # Set by engine if TUI is enabled

    def tick(self, proposal: str) -> Tuple[str, bool]:
        import os
        import threading
        
        if os.getenv("ARIADNE_AUTO_ACCEPT") == "true":
            logger.info("Auto-accepting proposal due to ARIADNE_AUTO_ACCEPT=true")
            return "ACCEPTED", True

        if self.app:
            # TUI Mode: Use message passing and wait for event
            from .tui import PromptUserMessage
            response_event = threading.Event()
            response_container = {"approved": False}
            
            self.app.post_message(PromptUserMessage(proposal, response_event, response_container))
            
            # This blocks the engine thread, but NOT the TUI thread
            response_event.wait()
            approved = response_container["approved"]
            return "ACCEPTED" if approved else "REJECTED", approved
        else:
            # CLI Mode: Use standard input
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
    Surgical string replacement within a specific AST node's byte range.
    Input Payload: Dict with 'filepath', 'edits' (list of dicts).
    Edits can have:
    - 'new_code': Direct replacement of the entire node range.
    - 'search_text' & 'replace_text': Legacy search-and-replace within the node range.
    Returns: Tuple[str, str] (status, filepath)
    """

    def __init__(self):
        super().__init__("BLOCK_SPLICE")

    def tick(self, payload: Dict[str, Any]) -> Tuple[str, str]:
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
                        logger.error(f"BlockSplice rejected: search_text not found in target node.")
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
            with open(filepath, "wb") as f:
                f.write(new_source_code)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass

            return "SUCCESS", filepath
        except Exception as e:
            logger.error(f"BlockSplice Error: {e}")
            return "ERROR", str(e)
