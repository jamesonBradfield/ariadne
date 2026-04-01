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
from .primitives import ExtractAST, QueryLLM, ExecuteCommand, PromptUser, WriteFile, ASTSplice, BlockSplice
from .components import TreeSitterSensor

logger = logging.getLogger("ariadne.states")


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
            {"input": payload.get("input", "")}
        )

        query = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        status, technical_intent = query.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": model_info.get("params", {})
        })

        if status != "SUCCESS":
            return "ABORT", JobPayload(intent="Failed to triage")

        job = JobPayload(
            intent=technical_intent.strip(),
            target_files=payload.get("target_files", [])
        )
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
            status, result = self.profile.get_skeleton(f)
            if status == "SUCCESS":
                skeletons.append(f"File: {f}\n{result}")

        skeleton_context = "\n\n".join(skeletons)

        model_info = self.config_manager.get_model_info("DISPATCH")
        state_config = self.config_manager.config["states"]["DISPATCH"]
        
        system_prompt = self.config_manager.render_prompt(state_config["system_prompt"], {"language": self.profile.name})
        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {"intent": job.intent, "skeleton_context": skeleton_context, "language": self.profile.name}
        )

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
        
        job.test_stdout = output
        
        if status == "SUCCESS":
            logger.info("Tests PASSED! Goal achieved.")
            return "SUCCESS", job
        else:
            logger.warning("Tests FAILED. Analyzing output...")
            
            failing_file, failing_line = self._parse_failure(output)
            if failing_file and failing_line:
                logger.info(f"Detected failure at {failing_file}:{failing_line}. Transitioning to INTERVENE.")
                job.failing_file = failing_file
                job.failing_line = failing_line
                return "INTERVENE", job

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
        app = getattr(payload, "app", None) if hasattr(payload, "app") else payload.get("app")
        # Check if we injected app into the states or payload
        # Better: PromptUser primitive already has self.app. Let's try to find it.
        
        if app:
            from .tui import EditorMessage
            completion_event = threading.Event()
            app.post_message(EditorMessage(command, completion_event))
            completion_event.wait()
        else:
            subprocess.run(shlex.split(command))

    def tick(self, payload: Any) -> Tuple[str, Any]:
        editor_cfg = self.config_manager.config.get("editor", {})
        if editor_cfg.get("headless", False):
            next_state = getattr(payload, "next_headless_state", "ROUTER") if hasattr(payload, "next_headless_state") else payload.get("next_headless_state", "ROUTER")
            return next_state, payload

        command_template = editor_cfg.get("command_template", "nvim +{line} {file}")
        
        # Scenario A: Intent Elaboration
        needs_elaboration = getattr(payload, "needs_elaboration", False) if hasattr(payload, "needs_elaboration") else payload.get("needs_elaboration", False)
        if needs_elaboration:
            intent = getattr(payload, "intent", "") if hasattr(payload, "intent") else payload.get("intent", "")
            with tempfile.NamedTemporaryFile(suffix=".md", mode='w+', delete=False) as tf:
                tf.write("# Ariadne Intent Elaboration\n")
                tf.write("Edit the text below to refine the coding objective. Save and exit to continue.\n\n")
                tf.write(intent)
                temp_path = tf.name
            
            cmd = command_template.format(line=4, file=temp_path)
            logger.info(f"Opening editor for intent elaboration: {cmd}")
            self._open_editor(cmd, payload)
            
            with open(temp_path, 'r') as f:
                content = f.read()
                parts = content.split('\n\n', 1)
                new_intent = parts[-1].strip() if len(parts) > 1 else content.strip()
            
            os.unlink(temp_path)
            
            if isinstance(payload, JobPayload):
                payload.intent = new_intent
                payload.needs_elaboration = False
            else:
                payload["intent"] = new_intent
                payload["needs_elaboration"] = False
                
            return "TRIAGE", payload

        # Scenario B: Manual Fix Intervention
        failing_file = getattr(payload, "failing_file", None) if hasattr(payload, "failing_file") else payload.get("failing_file")
        if failing_file:
            line = getattr(payload, "failing_line", "1") if hasattr(payload, "failing_line") else payload.get("failing_line", "1")
            cmd = command_template.format(line=line, file=failing_file)
            logger.info(f"Opening editor for manual fix: {cmd}")
            self._open_editor(cmd, payload)
            
            if isinstance(payload, JobPayload):
                if hasattr(payload, "failing_file"):
                    delattr(payload, "failing_file")
                if hasattr(payload, "failing_line"):
                    delattr(payload, "failing_line")
            else:
                if "failing_file" in payload:
                    del payload["failing_file"]
                if "failing_line" in payload:
                    del payload["failing_line"]
                
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
            status, result = self.profile.get_skeleton(f)
            if status == "SUCCESS":
                skeletons.append(f"File: {f}\n{result}")
        
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
            return "ABORT", job

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
                "plan": json.dumps(job.plan)
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
            return "ABORT", job

        next_state = decision.get("next_state", "ABORT")
        logger.info(f"Router decision: {next_state} (Reasoning: {decision.get('reasoning')})")
        
        job.retry_count += 1
        if job.retry_count > 10:
            logger.error("Max retries exceeded. Aborting.")
            return "ABORT", job

        return next_state, job


class SEARCH(State):
    """
    Maps symbols from the plan to concrete code locations.
    """
    def __init__(self, config_manager, profile):
        super().__init__("SEARCH")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info("Searching for target symbols...")
        
        if not job.plan or "steps" not in job.plan:
            logger.error("No plan steps found in SEARCH state.")
            return "THINKING", job

        extracted_nodes = []
        for step in job.plan["steps"]:
            symbol = step["symbol"]
            for filepath in job.target_files:
                status, nodes = self.profile.find_symbol(filepath, symbol)
                if status == "SUCCESS" and nodes:
                    for node in nodes:
                        extracted_nodes.append({
                            "filepath": filepath,
                            "symbol": symbol,
                            "node_string": node["code"],
                            "start_byte": node["start_byte"],
                            "end_byte": node["end_byte"],
                            "node_type": node["type"]
                        })
                    break
        
        if not extracted_nodes:
            logger.warning("No symbols from plan were found in codebase.")
            return "THINKING", job

        job.extracted_nodes = extracted_nodes
        job.maps_state = {"current_target_index": 0}
        return "SENSE", job


class SENSE(State):
    """
    Re-validates byte-offsets before surgeon operations.
    """
    def __init__(self, profile):
        super().__init__("SENSE")
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        return "MAPS", job


class MAPS(State):
    """
    Surgeon state. Generates surgical SEARCH/REPLACE patches for AST nodes.
    """
    def __init__(self, config_manager, profile):
        super().__init__("MAPS")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        idx = job.maps_state["current_target_index"]
        if idx >= len(job.extracted_nodes):
            return "SYNTAX_GATE", job

        target_node = job.extracted_nodes[idx]
        logger.info(f"MAPS operating on {target_node['symbol']} ({idx+1}/{len(job.extracted_nodes)})")

        model_info = self.config_manager.get_model_info("MAPS")
        state_config = self.config_manager.config["states"]["MAPS"]

        error_context = ""
        if hasattr(job, "llm_feedback") and job.llm_feedback:
            error_context = f"PREVIOUS ATTEMPT FAILED SYNTAX CHECK:\n{job.llm_feedback}\nPlease correct your SEARCH/REPLACE logic."

        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "intent": job.intent,
                "error_context": error_context,
                "current_symbol": target_node["symbol"],
                "current_node_type": target_node["node_type"],
                "node_text": target_node["node_string"]
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
            job.llm_feedback = f"Failed to generate valid SEARCH/REPLACE block: {result}"
            return "ROUTER", job

        job.fixed_code = {
            "filepath": target_node["filepath"],
            "edits": [{
                "start_byte": target_node["start_byte"],
                "end_byte": target_node["end_byte"],
                "search_text": result["search"],
                "replace_text": result["replace"]
            }]
        }
        
        job.maps_state["current_target_index"] += 1
        return "SYNTAX_GATE", job


class SYNTAX_GATE(State):
    """
    Validates generated code syntax before disk write.
    """
    def __init__(self, profile):
        super().__init__("SYNTAX_GATE")
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info("Validating syntax of proposed edits...")
        
        if not job.fixed_code:
            return "ACTUATE", job

        sensor = TreeSitterSensor(self.profile.language_ptr)
        
        with open(job.fixed_code["filepath"], "rb") as f:
            source = f.read()

        edit = job.fixed_code["edits"][0]
        node_text = source[edit["start_byte"]:edit["end_byte"]].decode("utf-8")
        
        search_norm = edit["search_text"].replace("\r\n", "\n")
        replace_norm = edit["replace_text"].replace("\r\n", "\n")
        node_norm = node_text.replace("\r\n", "\n")

        if search_norm not in node_norm:
            job.llm_feedback = "The SEARCH block did not match the source code exactly."
            return "ROUTER", job

        new_node_text = node_norm.replace(search_norm, replace_norm, 1)
        
        is_valid, error = sensor.validate_repair(source, [{
            "start_byte": edit["start_byte"],
            "end_byte": edit["end_byte"],
            "new_code": new_node_text
        }])

        if not is_valid:
            logger.error(f"Syntax validation failed: {error}")
            job.llm_feedback = f"Syntax error in generated code: {error}"
            return "ROUTER", job

        logger.info("Syntax validation passed.")
        job.llm_feedback = None
        return "ACTUATE", job


class ACTUATE(State):
    """
    Splices patches into the source file.
    """
    def __init__(self):
        super().__init__("ACTUATE")

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        logger.info("Actuating surgical edits to disk...")
        
        if not job.fixed_code:
            return "EVALUATE", job

        splicer = BlockSplice()
        status, result = splicer.tick(job.fixed_code)

        if status == "SUCCESS":
            if job.maps_state["current_target_index"] < len(job.extracted_nodes):
                return "SENSE", job
            return "EVALUATE", job
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
