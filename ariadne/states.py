import logging
import os
import re
import json
from typing import Any, Tuple, Dict, List, Optional, Union
from .core import State, EngineContext
from .payloads import (
    JobPayload,
    DispatchResponse,
    ThinkingResponse,
    MapsNavResponse,
    MapsThinkResponse,
    MapsSurgeonResponse,
    FileExplorerResponse,
    SpawnResponse,
    SelfOptimizationResponse,
)
from .primitives import (
    ExtractAST,
    QueryLLM,
    ExecuteCommand,
    PromptUser,
    WriteFile,
    ASTSplice,
    BlockSplice,
    QueryMCP,
    QueryAstGrep,
)
from .components import TreeSitterSensor

logger = logging.getLogger("ariadne.states")


def record_interaction(
    context: EngineContext, state: str, system: str, user: str, response: Any
):
    """Logs an LLM interaction to the job history for self-optimization."""
    from .payloads import InteractionTrace

    # If response is a Pydantic model, dump it to JSON string
    resp_str = ""
    if hasattr(response, "model_dump_json"):
        resp_str = response.model_dump_json()
    else:
        resp_str = str(response)

    trace = InteractionTrace(
        state=state, system_prompt=system, user_prompt=user, response=resp_str
    )
    context.interaction_history.append(trace)


class DISPATCH(State):
    """
    Generates a test contract based on the language profile and skeletons.
    """

    def __init__(
        self, config_manager, test_filepath: str, profile, target_files: List[str]
    ):
        super().__init__("DISPATCH")
        self.config_manager = config_manager
        self.test_filepath = test_filepath
        self.profile = profile
        self.target_files = target_files
        self.prompt_user = PromptUser()

    def tick(self, job: JobPayload, context: EngineContext) -> Tuple[str, JobPayload]:
        logger.info(f"Generating test contract for {self.profile.name}...")

        skeletons = []
        for f in self.target_files:
            if not os.path.exists(f):
                continue
            status, result = self.profile.get_skeleton(f)
            if status == "SUCCESS":
                skeletons.append(f"File: {f}\n{result}")
            else:
                try:
                    with open(f, "r", encoding="utf-8") as src:
                        skeletons.append(f"File: {f} (Full Source)\n{src.read()}")
                except Exception:
                    pass

        skeleton_context = "\n\n".join(skeletons)

        model_info = self.config_manager.get_model_info("DISPATCH")
        state_config = self.config_manager.config["states"]["DISPATCH"]

        system_prompt = self.config_manager.render_prompt(
            state_config["system_prompt"], {"language": self.profile.name}
        )
        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "intent": context.intent,
                "skeleton_context": skeleton_context,
                "language": self.profile.name,
            },
        )

        query = QueryLLM(
            model=model_info.get("model"), api_base=model_info.get("api_base")
        )
        status, result = query.tick(
            {
                "system": system_prompt,
                "user": user_prompt,
                "params": model_info.get("params", {}),
                "response_model": DispatchResponse,
            },
            context,
        )

        if status != "SUCCESS":
            return "ABORT", job

        test_code = result.test_code

        # Inject standard headers
        standard_headers = self.profile.get_standard_headers()
        if standard_headers and standard_headers not in test_code:
            test_code = f"{standard_headers}\n{test_code}"

        record_interaction(context, "DISPATCH", system_prompt, user_prompt, result)

        proposal = f"Proposed Test Code ({self.test_filepath}):\n\n{test_code}"
        status, approved = self.prompt_user.tick(proposal, context)

        if not approved:
            logger.warning("User rejected the test contract. Aborting.")
            return "ABORT", job

        writer = WriteFile()
        writer.tick({"filepath": self.test_filepath, "content": test_code}, context)

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
        rust_comp = re.search(r"-->\s*(.+?):(\d+):(\d+)", output)
        if rust_comp:
            return rust_comp.group(1), rust_comp.group(2)

        # Rust panics
        rust_panic = re.search(r"panicked at .*?([^ ]+\.rs):(\d+):(\d+)", output)
        if rust_panic:
            return rust_panic.group(1), rust_panic.group(2)

        # Python tracebacks
        py_trace = re.search(r'File "(.+?)", line (\d+)', output)
        if py_trace:
            return py_trace.group(1), py_trace.group(2)

        return None, None

    def tick(self, job: JobPayload, context: EngineContext) -> Tuple[str, JobPayload]:
        logger.info(f"Executing test suite: {self.test_command}")

        executor = ExecuteCommand()
        status, output = executor.tick(self.test_command, context)

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
                logger.info(
                    f"Detected failure location at {failing_file}:{failing_line}. Hints added to payload."
                )
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

    def tick(
        self, payload: Union[JobPayload, Dict[str, Any]], context: EngineContext
    ) -> Tuple[str, JobPayload]:
        # Normalize to JobPayload if it's a dict (initial state scenario)
        if isinstance(payload, dict):
            job = JobPayload(
                intent=payload.get("intent", ""),
                target_files=payload.get("target_files", []),
                needs_elaboration=payload.get("needs_elaboration", False),
                next_headless_state=payload.get("next_headless_state", "MAPS_NAV"),
            )
        else:
            job = payload

        editor_cfg = self.config_manager.config.get("editor", {})
        headless = editor_cfg.get("headless", False)
        rpc_template = editor_cfg.get("rpc_command_template")

        if headless and not rpc_template:
            logger.warning(
                "Headless mode active but no rpc_command_template provided. Skipping intervention."
            )
            return job.next_headless_state, job

        command_template = (
            rpc_template
            if headless
            else editor_cfg.get("command_template", "nvim +{line} {file}")
        )

        auto_accept = os.getenv("ARIADNE_AUTO_ACCEPT") == "true"

        # Scenario A: Intent Elaboration
        if job.needs_elaboration:
            if auto_accept:
                logger.info("Auto-accepting intent elaboration.")
                job.needs_elaboration = False
                return "THINKING", job

            original_intent = context.intent
            with tempfile.NamedTemporaryFile(
                suffix=".md", mode="w", encoding="utf-8", delete=False
            ) as tf:
                tf.write("# Ariadne Intent Elaboration\n")
                tf.write("Edit the text below to refine your coding objective.\n")
                tf.write("Save and exit your editor to continue execution.\n")
                tf.write(
                    "────────────────────────────────────────────────────────────────────────\n\n"
                )
                tf.write(original_intent)
                temp_path = tf.name

            cmd = command_template.format(line=5, file=temp_path)

            if headless:
                # Emit event instead of direct subprocess if possible, or just emit and wait
                context.emit("EDITOR_OPEN", {"command": cmd, "file": temp_path})
                context.emit(
                    "USER_PROMPT",
                    {
                        "proposal": f"Please edit the intent file: {temp_path}\nPress 'yes' when done."
                    },
                )
                context.wait_for_user()
            else:
                context.emit(
                    "EDITOR_OPEN", {"command": cmd, "file": temp_path, "blocking": True}
                )

            with open(temp_path, "r", encoding="utf-8") as f:
                content = f.read()
                parts = content.split(
                    "────────────────────────────────────────────────────────────────────────",
                    1,
                )
                new_intent = parts[-1].strip() if len(parts) > 1 else content.strip()

            os.unlink(temp_path)

            context.intent = new_intent if new_intent else original_intent
            job.needs_elaboration = False

            return "THINKING", job

        # Scenario B: Manual Fix Intervention
        if job.failing_file:
            if auto_accept:
                logger.info(
                    f"Auto-accepting manual fix for {job.failing_file}. Skipping editor."
                )
                job.failing_file = None
                job.failing_line = None
                return "EVALUATE", job

            line = job.failing_line or "1"
            cmd = command_template.format(line=line, file=job.failing_file)

            context.emit("EDITOR_OPEN", {"command": cmd, "file": job.failing_file})
            context.emit(
                "USER_PROMPT",
                {
                    "proposal": f"File opened in your editor: {job.failing_file}\nPress 'yes' when you are done making changes."
                },
            )
            context.wait_for_user()

            job.failing_file = None
            job.failing_line = None

            return "EVALUATE", job

        return "MAPS_NAV", job


class THINKING(State):
    """
    Architect state. Analyzes failures and creates a logical repair plan.
    """

    def __init__(self, config_manager, profile):
        super().__init__("THINKING")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload, context: EngineContext) -> Tuple[str, JobPayload]:
        logger.info("Architecting repair plan...")

        skeletons = []
        for f in context.target_files:
            if not os.path.exists(f):
                continue
            status, result = self.profile.get_skeleton(f)
            if status == "SUCCESS":
                skeletons.append(f"File: {f}\n{result}")
            else:
                try:
                    with open(f, "r", encoding="utf-8") as src:
                        skeletons.append(f"File: {f} (Full Source)\n{src.read()}")
                except Exception:
                    pass

        skeleton_context = "\n\n".join(skeletons)
        symbols = self.profile.get_available_symbols(context.target_files, context)

        model_info = self.config_manager.get_model_info("THINKING")
        state_config = self.config_manager.config["states"]["THINKING"]

        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "intent": context.intent,
                "test_code": job.test_code,
                "test_stdout": job.test_stdout,
                "available_symbols": json.dumps(symbols),
                "skeletons": skeleton_context,
            },
        )

        query = QueryLLM(
            model=model_info.get("model"), api_base=model_info.get("api_base")
        )
        status, plan = query.tick(
            {
                "system": state_config["system_prompt"],
                "user": user_prompt,
                "params": model_info.get("params", {}),
                "response_model": ThinkingResponse,
            },
            context,
        )

        record_interaction(
            context, "THINKING", state_config["system_prompt"], user_prompt, plan
        )

        if status != "SUCCESS":
            return "ABORT", job

        job.plan = plan
        job.plan_history.append(plan.reasoning)

        # LSP Reference Search: Find all references for each step's symbol
        lsp_service = context.services.lsp
        if lsp_service and lsp_service.is_running():
            for step in plan.steps:
                try:
                    # Get references for the symbol
                    references = []
                    for filepath in context.target_files:
                        if not os.path.exists(filepath):
                            continue
                        try:
                            refs = lsp_service.find_references(filepath, step.symbol)
                            if refs:
                                references.extend(refs)
                        except Exception:
                            pass
                    step.references = references
                except Exception:
                    pass

        job.maps_state = {
            "current_step_index": 0,
            "steps": [step.model_dump() for step in plan.steps],
        }
        job.extracted_nodes = []

        return "MAPS_NAV", job


def get_lsp_manager(config_manager, job=None):
    if job and hasattr(job, "lsp_service"):
        return job.lsp_service

    if not hasattr(config_manager, "_lsp_service"):
        from .services import LSPService

        config_manager._lsp_service = LSPService()

    return config_manager._lsp_service


class MAPS_NAV(State):
    """
    1st Phase: Pure navigation. Locks onto the exact node ID.
    """

    def __init__(self, config_manager, profile):
        super().__init__("MAPS_NAV")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload, context: EngineContext) -> Tuple[str, JobPayload]:
        if hasattr(job, "tracked_nodes") and job.tracked_nodes:
            return "MAPS_THINK", job

        if not hasattr(job, "tracked_nodes"):
            job.tracked_nodes = []

        idx = job.maps_state.get("current_step_index", 0)
        steps = job.maps_state.get("steps", [])

        if idx >= len(steps):
            if job.tracked_nodes:
                return "MAPS_THINK", job
            else:
                return "FINISH", job

        current_step = steps[idx]
        symbol = current_step["symbol"]

        found_nodes = []
        for filepath in context.target_files:
            if not os.path.exists(filepath):
                continue
            try:
                status, nodes = self.profile.find_symbol(filepath, symbol, context)
                if status == "SUCCESS" and nodes:
                    found_nodes.extend(nodes)
            except Exception as e:
                logger.error(f"Error finding symbol {symbol} in {filepath}: {e}")
                continue

        if not found_nodes:
            logger.warning(f"Could not find symbol {symbol}. Skipping to next step.")
            job.maps_state["current_step_index"] += 1
            return "MAPS_NAV", job

        for node in found_nodes:
            job.tracked_nodes.append(
                {
                    "filepath": context.target_files[0],
                    "symbol": symbol,
                    "node_string": node["code"],
                    "start_byte": node["start_byte"],
                    "end_byte": node["end_byte"],
                    "node_type": node["node_type"],
                }
            )

        job.maps_state["current_step_index"] += 1
        if "navigation_stack" in job.maps_state:
            del job.maps_state["navigation_stack"]

        return "MAPS_NAV", job


class MAPS_THINK(State):
    """
    2nd Phase: Diagnosis and drafting. Plain-text markdown focus.
    """

    def __init__(self, config_manager, profile):
        super().__init__("MAPS_THINK")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload, context: EngineContext) -> Tuple[str, JobPayload]:
        if not hasattr(job, "tracked_nodes") or not job.tracked_nodes:
            return "MAPS_NAV", job

        node_to_edit = job.tracked_nodes[0]

        filepath = node_to_edit["filepath"]
        start_byte = node_to_edit["start_byte"]
        end_byte = node_to_edit["end_byte"]

        with open(filepath, "rb") as f:
            source = f.read()
        node_snippet = source[start_byte:end_byte].decode("utf-8", errors="replace")

        lsp_service = context.services.lsp
        diagnostics = "No LSP data."
        hover_info = "No hover data."

        if lsp_service and lsp_service.is_running():
            diagnostics = json.dumps(lsp_service.get_diagnostics(filepath), indent=2)
            hover_info = lsp_service.get_hover(filepath, 0, 0)

        model_info = self.config_manager.get_model_info("MAPS_THINK")
        state_config = self.config_manager.config["states"]["MAPS_THINK"]

        error_context = ""
        if getattr(job, "llm_feedback", None):
            error_context = f"PREVIOUS ATTEMPT FAILED:\n{job.llm_feedback}\n"

        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "intent": context.intent,
                "current_symbol": node_to_edit["symbol"],
                "error_context": error_context,
                "node_snippet": node_snippet,
                "hover_info": hover_info,
                "diagnostics": diagnostics,
            },
        )

        query = QueryLLM(
            model=model_info.get("model"), api_base=model_info.get("api_base")
        )
        status, result = query.tick(
            {
                "system": state_config["system_prompt"],
                "user": user_prompt,
                "params": model_info.get("params", {}),
                "response_model": MapsThinkResponse,
            },
            context,
        )

        record_interaction(
            context, "MAPS_THINK", state_config["system_prompt"], user_prompt, result
        )

        if status != "SUCCESS":
            job.llm_feedback = f"Failed to get structured diagnosis: {result}"
            return "MAPS_NAV", job

        if result.action == "skip":
            logger.info("MAPS_THINK chose to skip. No changes needed for this symbol.")
            job.tracked_nodes.pop(0)
            return "MAPS_THINK", job

        if result.action == "abort":
            return "MAPS_NAV", job

        job.maps_state["locked_node_id"] = node_to_edit.get("node_type", "unknown")
        job.maps_state["locked_range"] = (start_byte, end_byte)
        job.maps_state["draft_code"] = result.draft_code
        job.fixed_code = {"filepath": filepath, "edits": []}

        return "MAPS_SURGEON", job


class MAPS_SURGEON(State):
    """
    3rd Phase: Strict surgical formatting and Ghost Check validation.
    """

    def __init__(self, config_manager, profile):
        super().__init__("MAPS_SURGEON")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload, context: EngineContext) -> Tuple[str, JobPayload]:
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
                "target_id": job.maps_state["locked_node_id"],
            },
        )

        query = QueryLLM(
            model=model_info.get("model"), api_base=model_info.get("api_base")
        )
        status, result = query.tick(
            {
                "system": state_config["system_prompt"],
                "user": user_prompt,
                "params": model_info.get("params", {}),
                "response_model": MapsSurgeonResponse,
            },
            context,
        )

        record_interaction(
            context, "MAPS_SURGEON", state_config["system_prompt"], user_prompt, result
        )

        if status != "SUCCESS":
            job.llm_feedback = f"Failed to get structured surgical command: {result}"
            return "MAPS_NAV", job

        action = result.action
        code = result.code
        target_id = job.maps_state["locked_node_id"]
        id_map = job.maps_state["id_map"]

        t_start, t_end = id_map[target_id]
        edit = {"start_byte": t_start, "end_byte": t_end, "new_code": code}

        if action == "delete":
            edit["new_code"] = ""
        elif action == "insert_before":
            edit["end_byte"] = t_start
        elif action == "insert_after":
            edit["start_byte"] = t_end

        # GHOST CHECK
        lsp_service = context.services.lsp
        if lsp_service and lsp_service.is_running():
            filepath = job.fixed_code["filepath"]
            with open(filepath, "rb") as f:
                original_source = f.read()

            # Apply edit to shadow buffer
            temp_source = bytearray(original_source)
            temp_source[edit["start_byte"] : edit["end_byte"]] = edit[
                "new_code"
            ].encode("utf-8")
            shadow_content = temp_source.decode("utf-8", errors="replace")

            # Notify LSP
            old_diags = len(lsp_service.get_diagnostics(filepath))
            lsp_service.did_change(filepath, shadow_content)
            new_diags = len(lsp_service.get_diagnostics(filepath))

            logger.info(f"Ghost Check: Diagnostics {old_diags} -> {new_diags}")

            if new_diags > old_diags:
                logger.warning(
                    "Ghost Check failed: Diagnostics increased! Aborting edit."
                )
                job.llm_feedback = (
                    "Your edit introduced NEW compiler errors. Re-evaluating."
                )
                return "MAPS_THINK", job

        job.fixed_code["edits"].append(edit)
        return "ACTUATE", job


class ACTUATE(State):
    """
    Splices patches into the source file and prepares for the next step.
    """

    def __init__(self):
        super().__init__("ACTUATE")

    def tick(self, job: JobPayload, context: EngineContext) -> Tuple[str, JobPayload]:
        logger.info("Actuating surgical edits to disk...")

        if not job.fixed_code:
            return "MAPS_NAV", job

        splicer = BlockSplice()
        status, result = splicer.tick(job.fixed_code, context)

        if status == "SUCCESS":
            if job.tracked_nodes:
                job.tracked_nodes.pop(0)

            job.fixed_code = None
            if "navigation_stack" in job.maps_state:
                del job.maps_state["navigation_stack"]

            if job.tracked_nodes:
                return "MAPS_THINK", job
            else:
                return "MAPS_NAV", job
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

    def tick(self, job: JobPayload, context: EngineContext) -> Tuple[str, JobPayload]:
        logger.info("Repair session complete. summarized results.")

        # Self-Optimization Trigger: If we failed or had high retries
        if (job.retry_count > 3 or job.llm_feedback) and context.interaction_history:
            logger.info(
                "High retry count or feedback detected. Generating self-optimization case..."
            )

            model_info = self.config_manager.get_model_info("POST_MORTEM")
            state_config = self.config_manager.config["states"]["POST_MORTEM"]

            # Format history for the LLM - Limit to last 5 to keep context clean
            history_str = ""
            visible_history = context.interaction_history[-5:]
            for i, trace in enumerate(visible_history):
                history_str += f"\n--- Interaction {i} ({trace.state}) ---\n"
                history_str += f"System: {trace.system_prompt[:200]}...\n"
                history_str += f"User: {trace.user_prompt[:500]}...\n"
                history_str += f"Response: {trace.response[:500]}...\n"

            user_prompt = self.config_manager.render_prompt(
                state_config["user_prompt_template"], {"history": history_str}
            )

            query = QueryLLM(
                model=model_info.get("model"), api_base=model_info.get("api_base")
            )
            status, result = query.tick(
                {
                    "system": state_config["system_prompt"],
                    "user": user_prompt,
                    "params": model_info.get("params", {}),
                    "response_model": SelfOptimizationResponse,
                },
                context,
            )

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

                    logger.info(
                        f"Successfully recorded new optimization case to {case_file}"
                    )
                except Exception as e:
                    logger.error(f"Failed to save optimization case: {e}")

        return "FINISH", job


class FILE_EXPLORER(State):
    """
    AST-guided file explorer. Lets the LLM navigate the file system and see skeletons.
    """

    def __init__(self, config_manager, profile):
        super().__init__("FILE_EXPLORER")
        self.config_manager = config_manager
        self.profile = profile

    def tick(self, job: JobPayload, context: EngineContext) -> Tuple[str, JobPayload]:
        logger.info("Exploring files...")

        # Persistent navigation state
        if "explorer_path" not in job.maps_state:
            job.maps_state["explorer_path"] = "."

        current_dir = job.maps_state["explorer_path"]

        # Get Directory Listing
        try:
            items = os.listdir(current_dir)
            files = [f for f in items if os.path.isfile(os.path.join(current_dir, f))]
            dirs = [d for d in items if os.path.isdir(os.path.join(current_dir, d))]
        except Exception as e:
            job.llm_feedback = f"Error reading directory: {e}"
            job.maps_state["explorer_path"] = "."
            return "FILE_EXPLORER", job

        model_info = self.config_manager.get_model_info("FILE_EXPLORER")
        state_config = self.config_manager.config["states"]["FILE_EXPLORER"]

        # View of current location
        view = f"Current Directory: {current_dir}\n"
        view += "Directories: " + ", ".join(dirs) + "\n"
        view += "Files: " + ", ".join(files) + "\n"

        # If previewing a file, show skeleton
        if "preview_file" in job.maps_state:
            preview_path = job.maps_state["preview_file"]
            # Use AST navigation view with temporary IDs for cursor-based exploration
            with open(preview_path, "rb") as f:
                source = f.read()
            sensor = TreeSitterSensor(self.profile.get_language_ptr())
            ast_view, id_map = sensor.render_node_children(source, 0, len(source))
            view += f"\n--- AST PREVIEW: {preview_path} (Use 'dive <id>', 'rise', 'inspect') ---\n{ast_view}"
            job.maps_state["ast_id_map"] = id_map

        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"],
            {
                "intent": context.intent,
                "explorer_view": view,
                "llm_feedback": job.llm_feedback or "",
            },
        )

        query = QueryLLM(
            model=model_info.get("model"), api_base=model_info.get("api_base")
        )
        status, result = query.tick(
            {
                "system": state_config["system_prompt"],
                "user": user_prompt,
                "params": model_info.get("params", {}),
                "response_model": FileExplorerResponse,
            },
            context,
        )

        record_interaction(
            context, "FILE_EXPLORER", state_config["system_prompt"], user_prompt, result
        )

        if status != "SUCCESS":
            return "FILE_EXPLORER", job

        action = result.action
        target = result.target
        job.llm_feedback = None

        if action == "ls":
            # Refresh view essentially
            return "FILE_EXPLORER", job
        elif action == "cd":
            new_path = os.path.normpath(os.path.join(current_dir, target))
            if os.path.isdir(new_path):
                job.maps_state["explorer_path"] = new_path
                if "preview_file" in job.maps_state:
                    del job.maps_state["preview_file"]
            else:
                job.llm_feedback = f"'{target}' is not a directory."
            return "FILE_EXPLORER", job
        elif action == "up":
            job.maps_state["explorer_path"] = os.path.dirname(current_dir) or "."
            if "preview_file" in job.maps_state:
                del job.maps_state["preview_file"]
            return "FILE_EXPLORER", job
        elif action == "preview":
            preview_path = os.path.normpath(os.path.join(current_dir, target))
            if os.path.isfile(preview_path):
                job.maps_state["preview_file"] = preview_path
                # Initialize AST navigation context
                job.maps_state["ast_start"] = 0
                job.maps_state["ast_end"] = None
                job.maps_state["ast_stack"] = []
            else:
                job.llm_feedback = f"'{target}' is not a file."
            return "FILE_EXPLORER", job
        elif action == "dive":
            if (
                "ast_id_map" in job.maps_state
                and target in job.maps_state["ast_id_map"]
            ):
                start_byte, end_byte = job.maps_state["ast_id_map"][target]
                # Push current range to stack
                job.maps_state["ast_stack"].append(
                    (job.maps_state["ast_start"], job.maps_state["ast_end"])
                )
                # Update to selected node's range
                job.maps_state["ast_start"] = start_byte
                job.maps_state["ast_end"] = end_byte
            else:
                job.llm_feedback = f"Invalid node ID: {target}"
            return "FILE_EXPLORER", job
        elif action == "rise":
            if job.maps_state["ast_stack"]:
                job.maps_state["ast_start"], job.maps_state["ast_end"] = job.maps_state[
                    "ast_stack"
                ].pop()
            else:
                job.llm_feedback = "Already at root of AST"
            return "FILE_EXPLORER", job
        elif action == "spawn":
            # Transition to SPAWN state which will handle the multi-point investigation
            return "SPAWN", job

        return "FILE_EXPLORER", job


class SPAWN(State):
    """
    Converts 'spawn' targets into actual work items.
    """

    def __init__(self, config_manager):
        super().__init__("SPAWN")
        self.config_manager = config_manager

    def tick(self, job: JobPayload, context: EngineContext) -> Tuple[str, JobPayload]:
        logger.info("Spawning investigation points...")

        model_info = self.config_manager.get_model_info("SPAWN")
        state_config = self.config_manager.config["states"]["SPAWN"]

        user_prompt = self.config_manager.render_prompt(
            state_config["user_prompt_template"], {"intent": context.intent}
        )

        query = QueryLLM(
            model=model_info.get("model"), api_base=model_info.get("api_base")
        )
        status, result = query.tick(
            {
                "system": state_config["system_prompt"],
                "user": user_prompt,
                "params": model_info.get("params", {}),
                "response_model": SpawnResponse,
            },
            context,
        )

        record_interaction(
            context, "SPAWN", state_config["system_prompt"], user_prompt, result
        )

        if status != "SUCCESS":
            return "FILE_EXPLORER", job

        # Convert Spawn targets into ThinkingSteps
        steps = []
        for t in result.targets:
            # We assume t is a symbol name or file:symbol
            steps.append(ThinkingStep(symbol=t))

        plan = ThinkingResponse(reasoning=result.reasoning, steps=steps)
        job.plan = plan
        job.plan_history.append(f"Spawned investigation: {plan.reasoning}")

        job.maps_state = {
            "current_step_index": 0,
            "steps": [step.model_dump() for step in plan.steps],
        }
        job.extracted_nodes = []

        return "MAPS_NAV", job
