import logging
import os
import subprocess
import shlex
import tempfile
import re
import json
import threading
from typing import Any, Tuple, Dict, List, Optional, Union
from .core import State
from .payloads import (
    JobPayload, RouterResponse, DispatchResponse, ThinkingResponse, 
    MapsNavResponse, MapsThinkResponse, MapsSurgeonResponse,
    SelfOptimizationResponse
)
from .primitives import ExtractAST, QueryLLM, ExecuteCommand, PromptUser, WriteFile, ASTSplice, BlockSplice, QueryMCP, QueryAstGrep
from .lsp import LSPManager
from .components import TreeSitterSensor

logger = logging.getLogger("ariadne.states")

def record_interaction(job: JobPayload, state: str, system: str, user: str, response: Any):
    """Logs an LLM interaction to the job history for self-optimization."""
    from .payloads import InteractionTrace
    
    # If response is a Pydantic model, dump it to JSON string
    resp_str = ""
    if hasattr(response, "model_dump_json"):
        resp_str = response.model_dump_json()
    else:
        resp_str = str(response)

    trace = InteractionTrace(
        state=state,
        system_prompt=system,
        user_prompt=user,
        response=resp_str
    )
    job.interaction_history.append(trace)

class TRIAGE(State):
    """
    Initial state to distill user intent into a technical objective.
    """
    def __init__(self, config_manager):
        super().__init__("TRIAGE")
        self.config_manager = config_manager

    def tick(self, payload: Union[JobPayload, Dict[str, Any]]) -> Tuple[str, JobPayload]:
        logger.info("Triaging intent...")
        
        # Normalize to dict for easy access if needed
        is_job = hasattr(payload, "intent")
        intent_val = payload.intent if is_job else payload.get("intent", "")
        input_val = intent_val or (payload.get("input", "") if not is_job else "")

        model_info = self.config_manager.get_model_info("TRIAGE")
        state_config = self.config_manager.config["states"]["TRIAGE"]
        
        system_prompt = state_config["system_prompt"]
        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {"input": input_val}
        )

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, technical_intent = query.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": model_info.get("params", {})
        })

        if status != "SUCCESS":
             # Error handling
             return "ABORT", (payload if is_job else JobPayload(intent="Failed to triage"))

        # Handle LLM refusals
        if "I cannot" in technical_intent or "I am an AI" in technical_intent:
            logger.error("LLM refused to triage the intent. Check prompts or model safety settings.")
            return "ABORT", (payload if is_job else JobPayload(intent=f"LLM Refusal: {technical_intent}"))

        # AMNESIA CHECK: If the LLM echoed instructions, discard it
        clean_intent = technical_intent.strip()
        if "Task:" in clean_intent or "Analyze the Request" in clean_intent or "Output:" in clean_intent or "Constraint:" in clean_intent:
            logger.warning("TRIAGE generated noisy or mirrored output. Discarding and using original user input.")
            clean_intent = input_val

        if is_job:
            payload.intent = clean_intent
            return "DISPATCH", payload
        
        job = JobPayload(
            intent=clean_intent,
            target_files=payload.get("target_files", [])
        )
        # Preserve app reference
        job.app = payload.get("app")

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
        if job.app:
            self.prompt_user.app = job.app

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, result = query.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": model_info.get("params", {}),
            "response_model": DispatchResponse
        })
        
        if status != "SUCCESS":
            return "ABORT", job

        test_code = result.test_code
        
        # Inject standard headers
        standard_headers = self.profile.get_standard_headers()
        if standard_headers and standard_headers not in test_code:
            test_code = f"{standard_headers}\n{test_code}"

        record_interaction(job, "DISPATCH", system_prompt, user_prompt, result)

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

    def _open_editor(self, command: str, job: JobPayload) -> None:
        """Helper to open editor safely in TUI or CLI mode."""
        if job.app:
            from .tui import EditorMessage
            completion_event = threading.Event()
            job.app.post_message(EditorMessage(command, completion_event))
            completion_event.wait()
        else:
            subprocess.run(shlex.split(command))

    def tick(self, payload: Union[JobPayload, Dict[str, Any]]) -> Tuple[str, JobPayload]:
        # Normalize to JobPayload if it's a dict (initial state scenario)
        if isinstance(payload, dict):
            job = JobPayload(
                intent=payload.get("intent", ""),
                target_files=payload.get("target_files", []),
                needs_elaboration=payload.get("needs_elaboration", False),
                next_headless_state=payload.get("next_headless_state", "ROUTER"),
                app=payload.get("app")
            )
        else:
            job = payload

        editor_cfg = self.config_manager.config.get("editor", {})
        headless = editor_cfg.get("headless", False)
        rpc_template = editor_cfg.get("rpc_command_template")

        if headless and not rpc_template:
            logger.warning("Headless mode active but no rpc_command_template provided. Skipping intervention.")
            return job.next_headless_state, job

        command_template = rpc_template if headless else editor_cfg.get("command_template", "nvim +{line} {file}")
        
        auto_accept = os.getenv("ARIADNE_AUTO_ACCEPT") == "true"
        
        # Scenario A: Intent Elaboration
        if job.needs_elaboration:
            if auto_accept:
                logger.info("Auto-accepting intent elaboration.")
                job.needs_elaboration = False
                return "TRIAGE", job

            original_intent = job.intent
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
                self._open_editor(cmd, job)
            
            with open(temp_path, 'r', encoding='utf-8') as f:
                content = f.read()
                parts = content.split('────────────────────────────────────────────────────────────────────────', 1)
                new_intent = parts[-1].strip() if len(parts) > 1 else content.strip()
            
            os.unlink(temp_path)
            
            job.intent = new_intent if new_intent else original_intent
            job.needs_elaboration = False
                
            return "TRIAGE", job

        # Scenario B: Manual Fix Intervention
        if job.failing_file:
            if auto_accept:
                logger.info(f"Auto-accepting manual fix for {job.failing_file}. Skipping editor.")
                job.failing_file = None
                job.failing_line = None
                return "EVALUATE", job

            line = job.failing_line or "1"
            cmd = command_template.format(line=line, file=job.failing_file)
            
            if headless:
                logger.info(f"Sending failing file to remote editor via RPC: {cmd}")
                subprocess.run(cmd, shell=True)
                print("\n" + "="*60)
                print(f"Action Required: File opened in your remote editor via RPC: {job.failing_file}")
                input("Press Enter here in the terminal when you are done making changes...")
                print("="*60 + "\n")
            else:
                logger.info(f"Opening editor for manual fix: {cmd}")
                self._open_editor(cmd, job)
            
            job.failing_file = None
            job.failing_line = None
                
            return "EVALUATE", job

        return "ROUTER", job


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
            "response_model": ThinkingResponse
        })
        
        record_interaction(job, "THINKING", state_config["system_prompt"], user_prompt, plan)

        # LIVE OPTIMIZATION: Catch "Struct-Traps" early
        # if optimize_state_prompt(self.config_manager, "THINKING", user_prompt, plan):
        #     job.llm_feedback = "The Architect's plan was flawed (likely targeting a struct for a method). Retrying with better rules..."
        #     return "THINKING", job

        if status != "SUCCESS":
            return "ROUTER", job

        job.plan = plan
        job.plan_history.append(plan.reasoning)
        
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
                "llm_feedback": job.llm_feedback or "None",
                "plan": job.plan.model_dump_json() if job.plan else "None",
                "docs": job.docs or "None"
            }
        )

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, decision = query.tick({
            "system": state_config["system_prompt"],
            "user": user_prompt,
            "params": model_info.get("params", {}),
            "response_model": RouterResponse
        })
        
        record_interaction(job, "ROUTER", state_config["system_prompt"], user_prompt, decision)

        if status != "SUCCESS":
            logger.warning(f"Router received invalid response ({status}). Attempting recovery...")
            if job.retry_count < 3:
                return "THINKING", job
            return "INTERVENE", job

        next_state = decision.next_state
        logger.info(f"Router decision: {next_state} (Reasoning: {decision.reasoning})")
        
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
        
        if not job.plan or not getattr(job.plan, "steps", None):
            logger.error("No plan steps found in SEARCH state.")
            return "THINKING", job

        # NEW: Initialize the surgeon loop state
        job.maps_state = {
            "current_step_index": 0,
            "steps": [step.model_dump() for step in job.plan.steps]
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
        return "MAPS_NAV", job


_lsp_manager = None

def get_lsp_manager(config_manager, job: Optional[JobPayload] = None):
    global _lsp_manager
    if _lsp_manager is None:
        mcp_cfg = config_manager.config.get("mcp", {})
        if mcp_cfg.get("enabled", False):
            _lsp_manager = LSPManager(mcp_cfg.get("command"), mcp_cfg.get("args", []), cwd=os.getcwd())
    return _lsp_manager

class MAPS_NAV(State):
    """
    1st Phase: Pure navigation. Locks onto the exact node ID.
    """
    def __init__(self, config_manager, profile):
        super().__init__("MAPS_NAV")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        if not job.extracted_nodes:
            return "SENSE", job

        target_node = job.extracted_nodes[0]
        filepath = target_node["filepath"]
        
        # Initialize navigation state if not present
        if "navigation_stack" not in job.maps_state:
            job.maps_state["navigation_stack"] = [(target_node["start_byte"], target_node["end_byte"])]
            job.fixed_code = {"filepath": filepath, "edits": []}
        
        start_byte, end_byte = job.maps_state["navigation_stack"][-1]
        
        # Render AST View
        sensor = TreeSitterSensor(self.profile.get_language_ptr())
        with open(filepath, "rb") as f:
            source = f.read()
        ast_view, id_map = sensor.render_node_children(source, start_byte, end_byte)
        
        # Inject LSP Diagnostics if available
        lsp = get_lsp_manager(self.config_manager)
        if lsp:
            diagnostics = lsp.get_diagnostics(filepath)
            if diagnostics:
                ast_view += "\n\nLSP DIAGNOSTICS FOR THIS FILE:\n" + json.dumps(diagnostics, indent=2)

        model_info = self.config_manager.get_model_info("MAPS_NAV")
        state_config = self.config_manager.config["states"]["MAPS_NAV"]

        idx = job.maps_state.get("current_step_index", 0)
        steps = job.maps_state.get("steps", [])
        current_symbol = steps[idx]["symbol"] if idx < len(steps) else "Unknown"

        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "intent": job.intent,
                "current_symbol": current_symbol,
                "error_context": getattr(job, "llm_feedback", "") or "",
                "ast_view": ast_view
            }
        )

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, result = query.tick({
            "system": state_config["system_prompt"],
            "user": user_prompt,
            "params": model_info.get("params", {}),
            "response_model": MapsNavResponse
        })
        
        record_interaction(job, "MAPS_NAV", state_config["system_prompt"], user_prompt, result)

        if status != "SUCCESS":
            job.llm_feedback = f"Failed to get structured navigation response: {result}"
            return "ROUTER", job

        action = result.action
        target_id = str(result.target_id)
        
        # Fuzzy ID Resolution: If the LLM sent a byte range like "123-456" instead of a short ID
        if target_id not in id_map:
            for sid, (start, end) in id_map.items():
                range_str = f"{start}-{end}"
                if target_id == range_str:
                    logger.info(f"Fuzzy resolved byte-range '{target_id}' to short ID '{sid}'")
                    target_id = sid
                    break

        if action == "zoom":
            if target_id in id_map:
                new_range = id_map[str(target_id)]
                if new_range == (start_byte, end_byte):
                    job.llm_feedback = f"You are already focused on node '{target_id}'. To move deeper, zoom into a child ID (0, 1, 2, etc.)."
                    return "MAPS_NAV", job
                job.maps_state["navigation_stack"].append(new_range)
                job.llm_feedback = None # Clear feedback on success
                return "MAPS_NAV", job
            else:
                job.llm_feedback = f"Invalid target_id for zoom: {target_id}. Available IDs: {list(id_map.keys())}"
                return "MAPS_NAV", job
        
        elif action == "up":
            if len(job.maps_state["navigation_stack"]) > 1:
                job.maps_state["navigation_stack"].pop()
                job.llm_feedback = None
                return "MAPS_NAV", job
            else:
                job.llm_feedback = "You are already at the top of the current symbol's AST view. You cannot go higher. If you need to edit a different part of the file, use 'select' on a visible node or 'abort' in the THINK phase."
                return "MAPS_NAV", job
        
        elif action == "select":
            if target_id is not None and str(target_id) in id_map:
                job.maps_state["locked_node_id"] = str(target_id)
                job.maps_state["locked_range"] = id_map[str(target_id)]
                job.maps_state["id_map"] = id_map # Save for Surgeon
                job.llm_feedback = None
                return "MAPS_THINK", job
            else:
                job.llm_feedback = f"Invalid target_id for select: {target_id}. Available IDs: {list(id_map.keys())}"
                return "MAPS_NAV", job

        job.llm_feedback = f"Unknown action: {action}"
        return "MAPS_NAV", job


class MAPS_THINK(State):
    """
    2nd Phase: Diagnosis and drafting. Plain-text markdown focus.
    """
    def __init__(self, config_manager, profile):
        super().__init__("MAPS_THINK")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        filepath = job.fixed_code["filepath"]
        start_byte, end_byte = job.maps_state["locked_range"]
        
        with open(filepath, "rb") as f:
            source = f.read()
        node_snippet = source[start_byte:end_byte].decode("utf-8", errors="replace")
        
        # In-memory diagnostics and hover info
        lsp = get_lsp_manager(self.config_manager)
        diagnostics = "No LSP data."
        hover_info = "No hover data."
        
        if lsp:
            diagnostics = json.dumps(lsp.get_diagnostics(filepath), indent=2)
            # Find a good position for hover (start of node)
            # This is a simplification; ideally we'd map byte to line/char
            hover_info = lsp.get_hover(filepath, 0, 0) # Placeholder

        model_info = self.config_manager.get_model_info("MAPS_THINK")
        state_config = self.config_manager.config["states"]["MAPS_THINK"]

        error_context = ""
        if getattr(job, "llm_feedback", None):
            error_context = f"PREVIOUS ATTEMPT FAILED:\n{job.llm_feedback}\n"

        idx = job.maps_state.get("current_step_index", 0)
        steps = job.maps_state.get("steps", [])
        current_symbol = steps[idx]["symbol"] if idx < len(steps) else "Unknown"

        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "intent": job.intent,
                "current_symbol": current_symbol,
                "error_context": error_context,
                "node_snippet": node_snippet,
                "hover_info": hover_info,
                "diagnostics": diagnostics
            }
        )

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, result = query.tick({
            "system": state_config["system_prompt"],
            "user": user_prompt,
            "params": model_info.get("params", {}),
            "response_model": MapsThinkResponse
        })
        
        record_interaction(job, "MAPS_THINK", state_config["system_prompt"], user_prompt, result)

        if status != "SUCCESS":
            job.llm_feedback = f"Failed to get structured diagnosis: {result}"
            return "ROUTER", job

        if result.action == "skip":
            logger.info("MAPS_THINK chose to skip. No changes needed for this symbol.")
            job.maps_state["current_step_index"] += 1
            job.fixed_code = None
            if "navigation_stack" in job.maps_state:
                del job.maps_state["navigation_stack"]
            return "SENSE", job

        if result.action == "abort":
            return "MAPS_NAV", job
        
        job.maps_state["draft_code"] = result.draft_code
        return "MAPS_SURGEON", job


class MAPS_SURGEON(State):
    """
    3rd Phase: Strict surgical formatting and Ghost Check validation.
    """
    def __init__(self, config_manager, profile):
        super().__init__("MAPS_SURGEON")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        model_info = self.config_manager.get_model_info("MAPS_SURGEON")
        state_config = self.config_manager.config["states"]["MAPS_SURGEON"]

        error_context = ""
        if getattr(job, "llm_feedback", None):
            error_context = f"PREVIOUS ATTEMPT FAILED:\n{job.llm_feedback}\n"

        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "error_context": error_context,
                "draft_code": job.maps_state["draft_code"],
                "target_id": job.maps_state["locked_node_id"]
            }
        )

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, result = query.tick({
            "system": state_config["system_prompt"],
            "user": user_prompt,
            "params": model_info.get("params", {}),
            "response_model": MapsSurgeonResponse
        })
        
        record_interaction(job, "MAPS_SURGEON", state_config["system_prompt"], user_prompt, result)

        if status != "SUCCESS":
            job.llm_feedback = f"Failed to get structured surgical command: {result}"
            return "ROUTER", job

        action = result.action
        code = result.code
        target_id = job.maps_state["locked_node_id"]
        id_map = job.maps_state["id_map"]
        
        t_start, t_end = id_map[target_id]
        edit = {"start_byte": t_start, "end_byte": t_end, "new_code": code}
        
        if action == "delete": edit["new_code"] = ""
        elif action == "insert_before": edit["end_byte"] = t_start
        elif action == "insert_after": edit["start_byte"] = t_end

        # GHOST CHECK
        lsp = get_lsp_manager(self.config_manager)
        if lsp:
            filepath = job.fixed_code["filepath"]
            with open(filepath, "rb") as f:
                original_source = f.read()
            
            # Apply edit to shadow buffer
            temp_source = bytearray(original_source)
            temp_source[edit["start_byte"]:edit["end_byte"]] = edit["new_code"].encode("utf-8")
            shadow_content = temp_source.decode("utf-8", errors="replace")
            
            # Notify LSP
            old_diags = len(lsp.get_diagnostics(filepath))
            lsp.did_change(filepath, shadow_content)
            new_diags = len(lsp.get_diagnostics(filepath))
            
            logger.info(f"Ghost Check: Diagnostics {old_diags} -> {new_diags}")
            
            if new_diags > old_diags:
                logger.warning("Ghost Check failed: Diagnostics increased! Aborting edit.")
                job.llm_feedback = "Your edit introduced NEW compiler errors. Re-evaluating."
                return "MAPS_THINK", job

        job.fixed_code["edits"].append(edit)
        return "SYNTAX_GATE", job


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
            if job.fixed_code and job.fixed_code.get("edits"):
                job.fixed_code["edits"].pop()
            return "MAPS_THINK", job

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
    Summarizes the repair session results and generates optimization cases on failure.
    """
    def __init__(self, config_manager):
        super().__init__("POST_MORTEM")
        self.config_manager = config_manager

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info("Repair session complete. summarized results.")
        
        # Self-Optimization Trigger: If we failed or had high retries
        if (job.retry_count > 3 or job.llm_feedback) and job.interaction_history:
            logger.info("High retry count or feedback detected. Generating self-optimization case...")
            
            model_info = self.config_manager.get_model_info("POST_MORTEM")
            state_config = self.config_manager.config["states"]["POST_MORTEM"]
            
            # Format history for the LLM - Limit to last 5 to keep context clean
            history_str = ""
            visible_history = job.interaction_history[-5:]
            for i, trace in enumerate(visible_history):
                history_str += f"\n--- Interaction {i} ({trace.state}) ---\n"
                history_str += f"System: {trace.system_prompt[:200]}...\n"
                history_str += f"User: {trace.user_prompt[:500]}...\n"
                history_str += f"Response: {trace.response[:500]}...\n"

            user_prompt = self.config_manager.render_prompt(
                state_config["user_prompt_template"],
                {"history": history_str}
            )

            query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
            status, result = query.tick({
                "system": state_config["system_prompt"],
                "user": user_prompt,
                "params": model_info.get("params", {}),
                "response_model": SelfOptimizationResponse
            })

            if status == "SUCCESS":
                case_file = "tests/llm_cases.json"
                try:
                    cases = []
                    if os.path.exists(case_file):
                        with open(case_file, "r") as f:
                            cases = json.load(f)
                    
                    cases.append(result.model_dump())
                    
                    with open(case_file, "w") as f:
                        json.dump(cases, f, indent=2)
                    
                    logger.info(f"Successfully recorded new optimization case to {case_file}")
                except Exception as e:
                    logger.error(f"Failed to save optimization case: {e}")

        return "FINISH", job
