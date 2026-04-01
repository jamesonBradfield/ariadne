import logging
import os
import subprocess
import shlex
import tempfile
import re
import json
import threading
from typing import Any, Tuple, Dict, List, Optional
from .core import State
from .payloads import JobPayload
from .primitives import ExtractAST, QueryLLM, ExecuteCommand, PromptUser, WriteFile, ASTSplice, BlockSplice, QueryMCP
from .components import TreeSitterSensor

logger = logging.getLogger("ariadne.states")

def get_payload_attr(payload: Any, attr: str, default: Any = None) -> Any:
    """Safely gets an attribute from either a JobPayload object or a dict."""
    if isinstance(payload, dict):
        return payload.get(attr, default)
    return getattr(payload, attr, default)

def set_payload_attr(payload: Any, attr: str, value: Any) -> None:
    """Safely sets an attribute on either a JobPayload object or a dict."""
    if isinstance(payload, dict):
        payload[attr] = value
    else:
        setattr(payload, attr, value)

class TRIAGE(State):
    """
    Initial state to distill user intent into a technical objective.
    """
    def __init__(self, config_manager):
        super().__init__("TRIAGE")
        self.config_manager = config_manager

    def tick(self, payload: Dict[str, Any]) -> Tuple[str, JobPayload]:
        logger.info("Triaging intent...")
        
        model_info = self.config_manager.get_model_info("TRIAGE")
        state_config = self.config_manager.config["states"]["TRIAGE"]
        
        system_prompt = state_config["system_prompt"]
        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {"input": get_payload_attr(payload, "input", "") or get_payload_attr(payload, "intent", "")}
        )

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, technical_intent = query.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": model_info.get("params", {})
        })

        if status != "SUCCESS":
            return "ABORT", JobPayload(intent="Failed to triage")

        # Handle LLM refusals
        if "I cannot" in technical_intent or "I am an AI" in technical_intent:
            logger.error("LLM refused to triage the intent. Check prompts or model safety settings.")
            return "ABORT", JobPayload(intent=f"LLM Refusal: {technical_intent}")

        job = JobPayload(
            intent=technical_intent.strip(),
            target_files=get_payload_attr(payload, "target_files", [])
        )
        # Preserve app reference
        job.app = get_payload_attr(payload, "app")

        return "DISPATCH", job


class DISPATCH(State):
    """
    Generates a test contract based on the language profile and skeletons.
    """
    def __init__(self, config_manager, test_filepath: str, profile, target_files: List[str]):
        super().__init__("DISPATCH")
        self.config_manager = config_manager
        self.test_filepath = test_filepath
        self.profile = profile
        self.target_files = target_files
        self.prompt_user = PromptUser()

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info(f"Generating test contract for {self.profile.name}...")

        skeletons = []
        for f in self.target_files:
            if not os.path.exists(f): continue
            status, result = self.profile.get_skeleton(f)
            if status == "SUCCESS":
                skeletons.append(f"File: {f}\n{result}")
            else:
                try:
                    with open(f, 'r', encoding='utf-8') as src:
                        skeletons.append(f"File: {f} (Full Source)\n{src.read()}")
                except Exception: pass

        skeleton_context = "\n\n".join(skeletons)

        model_info = self.config_manager.get_model_info("DISPATCH")
        state_config = self.config_manager.config["states"]["DISPATCH"]
        
        system_prompt = self.config_manager.render_prompt(state_config["system_prompt"], {"language": self.profile.name})
        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {"intent": job.intent, "skeleton_context": skeleton_context, "language": self.profile.name}
        )

        # Inject app into prompt_user for TUI support
        if hasattr(job, "app") and job.app:
            self.prompt_user.app = job.app

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, test_code = query.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": model_info.get("params", {}),
            "post_process": state_config.get("post_process")
        })

        if status != "SUCCESS":
            return "ABORT", job

        proposal = f"Proposed Test Code ({self.test_filepath}):\n\n{test_code}"
        status, approved = self.prompt_user.tick(proposal)

        if not approved:
            logger.warning("User rejected the test contract. Aborting.")
            return "ABORT", job

        writer = WriteFile()
        writer.tick({"filepath": self.test_filepath, "content": test_code})
        
        job.test_code = test_code
        return "EVALUATE", job


class EVALUATE(State):
    """
    Executes tests and captures output.
    """
    def __init__(self, test_command: str):
        super().__init__("EVALUATE")
        self.test_command = test_command

    def _parse_failure(self, output: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parses compiler/runtime output for file and line number.
        """
        # Rust compiler errors
        rust_comp = re.search(r'-->\s*(.+?):(\d+):(\d+)', output)
        if rust_comp:
            return rust_comp.group(1), rust_comp.group(2)
            
        # Rust panics
        rust_panic = re.search(r'panicked at .*?([^ ]+\.rs):(\d+):(\d+)', output)
        if rust_panic:
            return rust_panic.group(1), rust_panic.group(2)
            
        # Python tracebacks
        py_trace = re.search(r'File "(.+?)", line (\d+)', output)
        if py_trace:
            return py_trace.group(1), py_trace.group(2)
            
        return None, None

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info(f"Executing test suite: {self.test_command}")
        
        executor = ExecuteCommand()
        status, output = executor.tick(self.test_command)
        
        # Truncate output to prevent context overflow in subsequent LLM states
        if len(output) > 5000:
            logger.info(f"Truncating test output (original length: {len(output)})")
            output = output[:2500] + "\n... [TRUNCATED] ...\n" + output[-2500:]

        job.test_stdout = output
        
        if status == "SUCCESS":
            logger.info("Tests PASSED! Goal achieved.")
            return "SUCCESS", job
        else:
            logger.warning("Tests FAILED. Analyzing output...")
            
            failing_file, failing_line = self._parse_failure(output)
            if failing_file and failing_line:
                logger.info(f"Detected failure location at {failing_file}:{failing_line}. Hints added to payload.")
                job.failing_file = failing_file
                job.failing_line = failing_line

            return "THINKING", job


class INTERVENE(State):
    """
    Human-in-the-loop state for manual intervention via an external editor.
    """
    def __init__(self, config_manager):
        super().__init__("INTERVENE")
        self.config_manager = config_manager

    def _open_editor(self, command: str, payload: Any) -> None:
        """Helper to open editor safely in TUI or CLI mode."""
        app = get_payload_attr(payload, "app")
        if app:
            from .tui import EditorMessage
            completion_event = threading.Event()
            app.post_message(EditorMessage(command, completion_event))
            completion_event.wait()
        else:
            subprocess.run(shlex.split(command))

    def tick(self, payload: Any) -> Tuple[str, Any]:
        editor_cfg = self.config_manager.config.get("editor", {})
        headless = editor_cfg.get("headless", False)
        rpc_template = editor_cfg.get("rpc_command_template")

        if headless and not rpc_template:
            logger.warning("Headless mode active but no rpc_command_template provided. Skipping intervention.")
            next_state = get_payload_attr(payload, "next_headless_state", "ROUTER")
            return next_state, payload

        command_template = rpc_template if headless else editor_cfg.get("command_template", "nvim +{line} {file}")
        
        # Scenario A: Intent Elaboration
        needs_elaboration = get_payload_attr(payload, "needs_elaboration", False)
        if needs_elaboration:
            original_intent = get_payload_attr(payload, "intent", "")
            with tempfile.NamedTemporaryFile(suffix=".md", mode='w', encoding='utf-8', delete=False) as tf:
                tf.write("# Ariadne Intent Elaboration\n")
                tf.write("Edit the text below to refine your coding objective.\n")
                tf.write("Save and exit your editor to continue execution.\n")
                tf.write("────────────────────────────────────────────────────────────────────────\n\n")
                tf.write(original_intent)
                temp_path = tf.name
            
            cmd = command_template.format(line=5, file=temp_path)
            
            if headless:
                logger.info(f"Sending intent to remote editor via RPC: {cmd}")
                # Use shell=True on Windows to handle command templates more naturally
                subprocess.run(cmd, shell=True)
                print("\n" + "!"*60)
                print("ACTION REQUIRED: Intent file sent to remote editor.")
                print(f"File: {temp_path}")
                input("Press ENTER here when you have SAVED and CLOSED the file in your editor...")
                print("!"*60 + "\n")
            else:
                logger.info(f"Opening editor for intent elaboration: {cmd}")
                self._open_editor(cmd, payload)
            
            with open(temp_path, 'r', encoding='utf-8') as f:
                content = f.read()
                parts = content.split('────────────────────────────────────────────────────────────────────────', 1)
                new_intent = parts[-1].strip() if len(parts) > 1 else content.strip()
            
            os.unlink(temp_path)
            
            final_intent = new_intent if new_intent else original_intent
            set_payload_attr(payload, "intent", final_intent)
            set_payload_attr(payload, "needs_elaboration", False)
                
            return "TRIAGE", payload

        # Scenario B: Manual Fix Intervention
        failing_file = get_payload_attr(payload, "failing_file")
        if failing_file:
            line = get_payload_attr(payload, "failing_line", "1")
            cmd = command_template.format(line=line, file=failing_file)
            
            if headless:
                logger.info(f"Sending failing file to remote editor via RPC: {cmd}")
                subprocess.run(shlex.split(cmd))
                print("\n" + "="*60)
                print(f"Action Required: File opened in your remote editor via RPC: {failing_file}")
                input("Press Enter here in the terminal when you are done making changes...")
                print("="*60 + "\n")
            else:
                logger.info(f"Opening editor for manual fix: {cmd}")
                self._open_editor(cmd, payload)
            
            # Clear failing info after intervention
            if isinstance(payload, dict):
                payload.pop("failing_file", None)
                payload.pop("failing_line", None)
            else:
                if hasattr(payload, "failing_file"): delattr(payload, "failing_file")
                if hasattr(payload, "failing_line"): delattr(payload, "failing_line")
                
            return "EVALUATE", payload

        return "ROUTER", payload


class THINKING(State):
    """
    Architect state. Analyzes failures and creates a logical repair plan.
    """
    def __init__(self, config_manager, profile):
        super().__init__("THINKING")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info("Architecting repair plan...")

        skeletons = []
        for f in job.target_files:
            if not os.path.exists(f): continue
            status, result = self.profile.get_skeleton(f)
            if status == "SUCCESS":
                skeletons.append(f"File: {f}\n{result}")
            else:
                try:
                    with open(f, 'r', encoding='utf-8') as src:
                        skeletons.append(f"File: {f} (Full Source)\n{src.read()}")
                except Exception: pass
        
        skeleton_context = "\n\n".join(skeletons)
        symbols = self.profile.get_available_symbols(job.target_files)

        model_info = self.config_manager.get_model_info("THINKING")
        state_config = self.config_manager.config["states"]["THINKING"]
        
        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "intent": job.intent,
                "test_code": job.test_code,
                "test_stdout": job.test_stdout,
                "available_symbols": json.dumps(symbols),
                "skeletons": skeleton_context
            }
        )

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, plan = query.tick({
            "system": state_config["system_prompt"],
            "user": user_prompt,
            "params": model_info.get("params", {}),
            "post_process": state_config.get("post_process")
        })

        if status != "SUCCESS":
            return "ROUTER", job

        job.plan = plan
        
        if not hasattr(job, "plan_history"):
            job.plan_history = []
        job.plan_history.append(plan.get("reasoning", "Plan update"))
        
        return "ROUTER", job


class ROUTER(State):
    """
    Orchestrator state. Decides the next transition based on job context.
    """
    def __init__(self, config_manager):
        super().__init__("ROUTER")
        self.config_manager = config_manager

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info("Routing to next state...")

        model_info = self.config_manager.get_model_info("ROUTER")
        state_config = self.config_manager.config["states"]["ROUTER"]
        
        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "intent": job.intent,
                "retry_count": job.retry_count,
                "test_stdout": job.test_stdout,
                "llm_feedback": getattr(job, "llm_feedback", "None"),
                "plan": json.dumps(job.plan),
                "docs": getattr(job, "docs", "None")
            }
        )

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, decision = query.tick({
            "system": state_config["system_prompt"],
            "user": user_prompt,
            "params": model_info.get("params", {}),
            "post_process": state_config.get("post_process")
        })

        if status != "SUCCESS":
            logger.warning(f"Router received invalid response ({status}). Attempting recovery...")
            if job.retry_count < 3:
                return "THINKING", job
            return "INTERVENE", job

        next_state = decision.get("next_state", "ABORT")
        logger.info(f"Router decision: {next_state} (Reasoning: {decision.get('reasoning')})")
        
        job.retry_count += 1
        if job.retry_count > 10:
            logger.error("Max retries exceeded. Aborting.")
            return "ABORT", job

        return next_state, job


class SEARCH(State):
    """
    Prepares the Surgeon's work list from the plan.
    """
    def __init__(self, config_manager, profile):
        super().__init__("SEARCH")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info("Preparing Surgeon work list...")
        
        if not job.plan or "steps" not in job.plan:
            logger.error("No plan steps found in SEARCH state.")
            return "THINKING", job

        # NEW: Initialize the surgeon loop state
        job.maps_state = {
            "current_step_index": 0,
            "steps": job.plan["steps"]
        }
        job.extracted_nodes = [] # Clear previous sense results
        
        return "SENSE", job


class SENSE(State):
    """
    Re-validates byte-offsets for the CURRENT target symbol before surgery.
    """
    def __init__(self, profile):
        super().__init__("SENSE")
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        idx = job.maps_state.get("current_step_index", 0)
        steps = job.maps_state.get("steps", [])
        
        if idx >= len(steps):
            logger.info("Surgeon has processed all planned steps.")
            return "EVALUATE", job

        current_step = steps[idx]
        symbol = current_step["symbol"]
        
        logger.info(f"Sensing exact byte-coordinates for symbol: {symbol}...")
        
        # SEARCH for the symbol's CURRENT location on disk
        found_nodes = []
        for filepath in job.target_files:
            if not os.path.exists(filepath): continue
            try:
                status, nodes = self.profile.find_symbol(filepath, symbol)
                if status == "SUCCESS" and nodes:
                    for node in nodes:
                        found_nodes.append({
                            "filepath": filepath,
                            "symbol": symbol,
                            "node_string": node["code"],
                            "start_byte": node["start_byte"],
                            "end_byte": node["end_byte"],
                            "node_type": node["type"]
                        })
                    break # Found it in this file
            except Exception as e:
                logger.error(f"Sensing error for {symbol} in {filepath}: {e}")
                continue

        if not found_nodes:
            logger.warning(f"Could not sense location for {symbol}. Skipping to next step.")
            job.maps_state["current_step_index"] += 1
            return "SENSE", job

        # Store ONLY the current target node
        job.extracted_nodes = found_nodes 
        return "MAPS", job


class MAPS(State):
    """
    Surgeon state. Implements the recursive AST Drill-Down Protocol.
    """
    def __init__(self, config_manager, profile):
        super().__init__("MAPS")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        if not job.extracted_nodes:
            return "SENSE", job

        target_node = job.extracted_nodes[0]
        
        # Initialize navigation state if not present
        if "navigation_stack" not in job.maps_state:
            job.maps_state["navigation_stack"] = [(target_node["start_byte"], target_node["end_byte"])]
            job.fixed_code = {
                "filepath": target_node["filepath"],
                "edits": []
            }
        
        # Get current focus from stack
        start_byte, end_byte = job.maps_state["navigation_stack"][-1]
        
        # Render the current view
        sensor = TreeSitterSensor(self.profile.get_language_ptr())
        with open(target_node["filepath"], "rb") as f:
            source = f.read()
        
        ast_view, id_map = sensor.render_node_children(source, start_byte, end_byte)
        
        model_info = self.config_manager.get_model_info("MAPS")
        state_config = self.config_manager.config["states"]["MAPS"]

        error_context = ""
        if hasattr(job, "llm_feedback") and job.llm_feedback:
            error_context = f"PREVIOUS ATTEMPT FAILED SYNTAX CHECK:\n{job.llm_feedback}\n"

        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "intent": job.intent,
                "error_context": error_context,
                "ast_view": ast_view
            }
        )

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, result = query.tick({
            "system": state_config["system_prompt"],
            "user": user_prompt,
            "params": model_info.get("params", {}),
            "post_process": state_config.get("post_process")
        })

        if status != "SUCCESS":
            job.llm_feedback = f"Failed to get navigation action: {result}"
            return "ROUTER", job

        action = result.get("action")
        target_id = result.get("target_id")
        code = result.get("code", "")
        
        logger.info(f"MAPS Action: {action} on ID {target_id}")

        if action == "zoom":
            if target_id is not None and str(target_id) in id_map:
                new_range = id_map[str(target_id)]
                if new_range == (start_byte, end_byte):
                    job.llm_feedback = f"You are already focused on {target_id}. Did you mean to zoom into a child ID instead?"
                    return "MAPS", job
                job.maps_state["navigation_stack"].append(new_range)
                return "MAPS", job
            else:
                job.llm_feedback = f"Invalid target_id for zoom: {target_id}. Available IDs: {list(id_map.keys())}"
                return "MAPS", job

        elif action == "up":
            if len(job.maps_state["navigation_stack"]) > 1:
                job.maps_state["navigation_stack"].pop()
            else:
                job.llm_feedback = "You are already at the top of the current symbol's AST view. You cannot go higher. If you need to add a method, use 'insert_after' or 'insert_before' on a child of the current node, or finalize this symbol and request a different one."
            return "MAPS", job

        elif action in ["replace", "delete", "insert_before", "insert_after"]:
            if target_id is not None and str(target_id) in id_map:
                t_start, t_end = id_map[str(target_id)]
                
                edit = {"start_byte": t_start, "end_byte": t_end, "new_code": code}
                
                if action == "delete":
                    edit["new_code"] = ""
                elif action == "insert_before":
                    edit["end_byte"] = t_start
                elif action == "insert_after":
                    edit["start_byte"] = t_end
                
                job.fixed_code["edits"].append(edit)
                return "MAPS", job
            else:
                job.llm_feedback = f"Invalid target_id for {action}: {target_id}. Available IDs: {list(id_map.keys())}"
                return "MAPS", job

        elif action == "done":
            return "SYNTAX_GATE", job

        return "ROUTER", job


class SYNTAX_GATE(State):
    """
    Validates generated code syntax before disk write.
    """
    def __init__(self, profile):
        super().__init__("SYNTAX_GATE")
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info("Validating syntax of proposed repair...")
        
        if not job.fixed_code or not job.fixed_code.get("edits"):
            return "ACTUATE", job

        sensor = TreeSitterSensor(self.profile.get_language_ptr())
        
        with open(job.fixed_code["filepath"], "rb") as f:
            source = f.read()

        # Normalize line endings in all edits
        edits = []
        for edit in job.fixed_code["edits"]:
            edits.append({
                "start_byte": edit["start_byte"],
                "end_byte": edit["end_byte"],
                "new_code": edit["new_code"].replace("\r\n", "\n")
            })
        
        # Syntax check the entire file with all surgical repairs applied
        is_valid, error = sensor.validate_repair(source, edits)

        if not is_valid:
            logger.error(f"Syntax validation failed: {error}")
            job.llm_feedback = f"The proposed repair introduced a syntax error: {error}. Please ensure the code is complete and follows the language grammar."
            return "ROUTER", job

        logger.info("Syntax validation passed.")
        job.llm_feedback = None
        return "ACTUATE", job


class ACTUATE(State):
    """
    Splices patches into the source file and prepares for the next step.
    """
    def __init__(self):
        super().__init__("ACTUATE")

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info("Actuating surgical edits to disk...")
        
        if not job.fixed_code:
            job.maps_state["current_step_index"] += 1
            return "SENSE", job

        splicer = BlockSplice()
        status, result = splicer.tick(job.fixed_code)

        if status == "SUCCESS":
            # Successfully edited one symbol. Move to the next.
            job.maps_state["current_step_index"] += 1
            job.fixed_code = None # Clear current edit
            # Clear navigation state for the next symbol
            if "navigation_stack" in job.maps_state:
                del job.maps_state["navigation_stack"]
            return "SENSE", job
        else:
            logger.error(f"Actuation failed: {result}")
            return "ABORT", job


class POST_MORTEM(State):
    """
    Summarizes the repair session results.
    """
    def __init__(self, config_manager):
        super().__init__("POST_MORTEM")
        self.config_manager = config_manager

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info("Repair session complete. summarized results.")
        return "FINISH", job


class DOCS(State):
    """
    Retrieves and compresses documentation context using MCP or local search.
    """
    def __init__(self, config_manager):
        super().__init__("DOCS")
        self.config_manager = config_manager

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info("Retrieving documentation context...")

        model_info = self.config_manager.get_model_info("DOCS")
        state_config = self.config_manager.config["states"]["DOCS"]
        
        # 1. Determine documentation source
        # For Rust projects, we assume cargo doc has been run or we run it
        # In this session, it was already run.
        
        mcp_cfg = self.config_manager.config.get("mcp", {})
        if mcp_cfg.get("enabled", False):
            logger.info("Using MCP to retrieve docs...")
            query_mcp = QueryMCP()
            status, result = query_mcp.tick({
                "command": mcp_cfg.get("command"),
                "args": mcp_cfg.get("args", []),
                "tool_name": state_config.get("mcp_tool", "read_file"),
                "tool_args": {
                    "path": state_config.get("doc_index", "target/doc/index.html")
                }
            })
            if status == "SUCCESS":
                raw_docs = str(result)
            else:
                logger.warning(f"MCP failed to retrieve docs: {result}. Falling back to direct read.")
                raw_docs = "Failed to retrieve docs via MCP."
        else:
            # Fallback: direct read of index.html if it exists
            doc_path = state_config.get("doc_index", "target/doc/index.html")
            if os.path.exists(doc_path):
                try:
                    with open(doc_path, 'r', encoding='utf-8') as f:
                        raw_docs = f.read()
                except Exception as e:
                    raw_docs = f"Error reading docs: {e}"
            else:
                raw_docs = "No documentation found at " + doc_path

        # 2. Agentic Filter/Compression
        logger.info("Compressing documentation context...")
        
        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "intent": job.intent,
                "raw_docs": raw_docs[:3000] # Limit input to LLM to avoid context overflow
            }
        )

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, compressed_docs = query.tick({
            "system": state_config["system_prompt"],
            "user": user_prompt,
            "params": model_info.get("params", {}),
            "post_process": state_config.get("post_process")
        })

        if status == "SUCCESS":
            job.docs = compressed_docs
        else:
            job.docs = "Failed to compress docs."

        return "THINKING", job
