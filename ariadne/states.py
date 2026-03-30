import logging
from typing import Any, Tuple, Dict, List
from .core import State
from .payloads import JobPayload
from .primitives import ExtractAST, QueryLLM, ExecuteCommand, PromptUser, WriteFile, ASTSplice
from .components import TreeSitterSensor, SyntaxGate

logger = logging.getLogger("ariadne.parent_states")

class TRIAGE(State):
    """
    Initializes ContextPayload and determines user intent.
    """
    def __init__(self, config_manager: Any):
        super().__init__("TRIAGE")
        self.config_manager = config_manager
        self.config = config_manager.get_model_info("TRIAGE")
        self.query_llm = QueryLLM(model=self.config.get("model"), api_base=self.config.get("api_base"))

    def tick(self, payload: Any) -> Tuple[str, Any]:
        # Support both raw string and dict-based payload for flexibility
        if isinstance(payload, dict):
            raw_input = payload.get("input", "")
            # If intent is already there (e.g. from CLI flag), don't re-triage
            if payload.get("intent"):
                return "DISPATCH", payload
        else:
            raw_input = payload
            
        variables = {"input": raw_input}
        system_prompt = self.config_manager.render_prompt(self.config.get("system_prompt", ""), variables)
        user_prompt = self.config_manager.render_prompt(self.config.get("user_prompt_template", ""), variables)

        status, intent = self.query_llm.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": self.config.get("params", {}),
            "post_process": self.config.get("post_process")
        })
        
        if status != "SUCCESS":
            return "ERROR", intent
            
        if isinstance(payload, dict):
            payload["intent"] = intent
            return "DISPATCH", payload
            
        return "DISPATCH", intent

class DISPATCH(State):
    """
    Creates JobPayload, generates a test, and gets user approval.
    """
    def __init__(self, config_manager: Any, test_filepath: str, profile: Any, target_files: List[str] = None):
        super().__init__("DISPATCH")
        self.config_manager = config_manager
        self.config = config_manager.get_model_info("DISPATCH")
        self.test_filepath = test_filepath
        self.target_files = target_files or []
        self.profile = profile
        self.extractor = ExtractAST(profile.get_language_ptr())
        self.skeleton_query = profile.get_skeleton_query()
        self.query_llm = QueryLLM(model=self.config.get("model"), api_base=self.config.get("api_base"))
        self.prompt_user = PromptUser()
        self.write_file = WriteFile()

    def tick(self, payload: Any) -> Tuple[str, JobPayload]:
        if isinstance(payload, dict):
            intent = payload.get("intent", "")
            t_files = list(set(self.target_files + payload.get("target_files", [])))
        else:
            intent = payload
            t_files = self.target_files
            
        job = JobPayload(intent=intent, target_files=t_files)
        
        # 1. Get Skeleton for context
        all_skeletons = []
        for filepath in t_files:
            status, skeletons = self.extractor.tick({
                "filepath": filepath,
                "query_string": self.skeleton_query,
                "capture_name": self.profile.skeleton_capture_name
            })
            all_skeletons.extend(skeletons)
        
        skeleton_context = "\n".join(all_skeletons)
        
        # 2. Generate Test
        variables = {
            "language": self.profile.name,
            "intent": intent,
            "skeleton_context": skeleton_context
        }
        system_prompt = self.config_manager.render_prompt(self.config.get("system_prompt", ""), variables)
        user_prompt = self.config_manager.render_prompt(self.config.get("user_prompt_template", ""), variables)
        
        status, test_code = self.query_llm.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": self.config.get("params", {}),
            "post_process": self.config.get("post_process")
        })
        
        # 3. Prompt for Approval
        p_status, approved = self.prompt_user.tick(f"Proposed Test:\n{test_code}")
        
        if not approved:
            return "HALT", job
            
        # 4. Save Test
        self.write_file.tick({"filepath": self.test_filepath, "content": test_code})
        job.read_only_tests.append(self.test_filepath)
        
        return "EVALUATE", job

class EVALUATE(State):
    """
    Runs tests and routes based on pass/fail.
    """
    def __init__(self, test_command: str = "cargo test"):
        super().__init__("EVALUATE")
        self.test_command = test_command
        self.executor = ExecuteCommand()

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        if job.retry_count > 3:
            logger.error("Circuit breaker triggered: Too many retries.")
            return "ABORT", job
            
        status, output = self.executor.tick(self.test_command)
        
        if status == "SUCCESS":
            logger.info("Tests passed!")
            return "SUCCESS", job
        else:
            logger.warning("Tests failed. Transitioning to THINKING.")
            job.test_stdout = output
            job.retry_count += 1
            return "THINKING", job

class THINKING(State):
    """
    Strategic Architect: Analyzes errors and creates a high-level repair plan.
    """
    def __init__(self, config_manager: Any, profile: Any):
        super().__init__("THINKING")
        self.config_manager = config_manager
        self.profile = profile
        self.config = config_manager.get_model_info("THINKING")
        self.query_llm = QueryLLM(model=self.config.get("model"), api_base=self.config.get("api_base"))
        self.extractor = ExtractAST(profile.get_language_ptr())

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        # 1. Gather context from target files
        all_skeletons = []
        available_symbols = []
        
        for filepath in job.target_files:
            status, skeletons = self.extractor.tick({
                "filepath": filepath,
                "query_string": self.profile.get_skeleton_query(),
                "capture_name": self.profile.skeleton_capture_name
            })
            for s in skeletons:
                import re
                # Improved regex to handle optional visibility and various item types
                name_match = re.search(r"(?:pub\s+)?(?:fn|struct|class|impl|enum|trait)\s+(\w+)", s)
                if name_match:
                    available_symbols.append(name_match.group(1))
                all_skeletons.append(f"--- Symbol Definition ---\n{s}")
        
        # Read the test content that failed
        test_content = "Unknown"
        if job.read_only_tests:
            try:
                with open(job.read_only_tests[0], "r") as f:
                    test_content = f.read()
            except Exception:
                pass

        # 2. Get available symbols for the architect
        # Aggressively truncate errors and skeletons to keep local server happy
        variables = {
            "intent": job.intent,
            "test_code": test_content[:1000],
            "test_stdout": job.test_stdout[:1000] + "... [TRUNCATED]" if len(job.test_stdout) > 1000 else job.test_stdout,
            "retry_count": job.retry_count,
            "available_symbols": ", ".join(set(available_symbols)),
            "skeletons": "\n".join([s.split("{")[0].strip() for s in all_skeletons])[:1000], # Just signatures
            "plan_history": "\n".join([f"- {p}" for p in job.plan_history]) if job.plan_history else "None"
        }
        
        system_prompt = self.config_manager.render_prompt(self.config.get("system_prompt", ""), variables)
        user_prompt = self.config_manager.render_prompt(self.config.get("user_prompt_template", ""), variables)

        status, plan = self.query_llm.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": self.config.get("params", {}),
            "post_process": "extract_json"
        })

        if status == "SUCCESS" and isinstance(plan, dict):
            job.plan = plan
            reasoning = plan.get('reasoning', 'No reasoning provided')
            job.plan_history.append(reasoning) # Track history
            logger.info(f"[{self.name}] Generated Plan: {reasoning}")
            return "ROUTER", job
        
        logger.error(f"[{self.name}] Failed to generate logical plan. Status: {status}, Plan Type: {type(plan)}")
        if status != "SUCCESS":
             logger.error(f"[{self.name}] LLM Error Details: {plan}")
        else:
             logger.error(f"[{self.name}] Non-dict plan received. Raw content (truncated): {str(plan)[:500]}")
             
        return "ABORT", job

class ROUTER(State):
    """
    Orchestrator: Decides the next state dynamically based on context, errors, and plans.
    """
    def __init__(self, config_manager: Any):
        super().__init__("ROUTER")
        self.config_manager = config_manager
        self.config = config_manager.get_model_info("ROUTER")
        self.query_llm = QueryLLM(model=self.config.get("model"), api_base=self.config.get("api_base"))
        self.valid_transitions = ["SEARCH", "DISPATCH", "MAPS", "THINKING", "ABORT"]

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        # Read the test content that failed
        test_content = "Unknown"
        if job.read_only_tests:
            try:
                with open(job.read_only_tests[0], "r") as f:
                    test_content = f.read()
            except Exception:
                pass

        import json
        variables = {
            "intent": job.intent,
            "retry_count": job.retry_count,
            "test_stdout": job.test_stdout[:1000] + "... [TRUNCATED]" if len(job.test_stdout) > 1000 else job.test_stdout,
            "llm_feedback": job.llm_feedback,
            "plan": json.dumps(job.plan)
        }
        
        system_prompt = self.config_manager.render_prompt(self.config.get("system_prompt", ""), variables)
        user_prompt = self.config_manager.render_prompt(self.config.get("user_prompt_template", ""), variables)

        status, response = self.query_llm.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": self.config.get("params", {}),
            "post_process": "extract_json"
        })

        if status == "SUCCESS" and isinstance(response, dict):
            next_state = response.get("next_state", "").upper()
            reasoning = response.get("reasoning", "No reasoning provided")
            logger.info(f"[{self.name}] Decision: {next_state} | Reasoning: {reasoning}")
            
            if next_state in self.valid_transitions:
                # Clear transient feedback before transitioning
                job.llm_feedback = ""
                return next_state, job
            else:
                logger.error(f"[{self.name}] Invalid next_state requested: {next_state}. Defaulting to ABORT.")
                return "ABORT", job

        logger.error(f"[{self.name}] Failed to get routing decision. Status: {status}")
        return "ABORT", job

class SEARCH(State):
    """
    Coordinator: Uses the Logical Plan to acquire exact code coordinates.
    """
    def __init__(self, config_manager: Any, profile: Any):
        super().__init__("SEARCH")
        self.config_manager = config_manager
        self.profile = profile
        self.extractor = ExtractAST(profile.get_language_ptr())

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        # If we have a plan, use it deterministically
        if job.plan and "steps" in job.plan:
            job.target_symbols = [step["symbol"] for step in job.plan["steps"] if "symbol" in step]
            job.current_file_index = 0
            logger.info(f"[{self.name}] Plan-driven symbols: {job.target_symbols}")
            return "SENSE", job
            
        logger.error(f"[{self.name}] No plan found to guide search. Aborting.")
        return "ABORT", job

class SENSE(State):
    """
    Acquires the exact AST coordinates for target symbols.
    """
    def __init__(self, profile):
        super().__init__("SENSE")
        self.profile = profile
        self.sensor = TreeSitterSensor(profile.get_language_ptr())

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        if job.current_file_index >= len(job.target_files):
            logger.error(f"[{self.name}] Exhausted all files without finding any target symbols.")
            return "ABORT", job

        filepath = job.target_files[job.current_file_index]
        job.extracted_nodes = []

        if not job.target_symbols:
            logger.error(f"[{self.name}] No target symbols provided. Aborting.")
            return "ABORT", job

        for symbol in job.target_symbols:
            query = self.profile.get_query(symbol)
            node_data = self.sensor.extract_node(filepath, query, self.profile.target_capture_name)

            if node_data:
                node_data["symbol"] = symbol
                job.extracted_nodes.append(node_data)
                logger.info(f"[{self.name}] Target acquired in {filepath}: {symbol}")
            else:
                logger.warning(f"[{self.name}] Symbol not found in {filepath}: {symbol}")

        if not job.extracted_nodes:
            job.current_file_index += 1
            return "SENSE", job

        return "MAPS", job

class MAPS(State):
    """
    Micro AST Procedural Surgeon: Navigates AST recursively for precise byte-edits.
    """
    def __init__(self, config_manager: Any, profile: Any):
        super().__init__("MAPS")
        self.config_manager = config_manager
        self.config = config_manager.get_model_info("MAPS")
        self.llm = QueryLLM(model=self.config.get("model"), api_base=self.config.get("api_base"))
        self.profile = profile

    def _render_node(self, source_code: bytes, node: Any, max_lines: int = 3) -> str:
        text = source_code[node.start_byte:node.end_byte].decode("utf8")
        lines = text.splitlines()
        if len(lines) > max_lines:
            return f"{lines[0]}\n... [{len(lines)-2} lines hidden] ...\n{lines[-1]}"
        return text

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        if not job.extracted_nodes:
            return "SENSE", job

        if not hasattr(job, "maps_state"):
            job.maps_state = {
                "current_target_index": 0,
                "node_history": [] # Stack of (start_byte, end_byte)
            }
            job.fixed_code = {"edits": []}

        if job.maps_state["current_target_index"] >= len(job.extracted_nodes):
            # We finished navigating all symbols
            del job.maps_state
            return "SYNTAX_GATE", job

        filepath = job.target_files[job.current_file_index]
        target_info = job.extracted_nodes[job.maps_state["current_target_index"]]
        current_symbol = target_info["symbol"]

        # 1. Parse the file
        with open(filepath, "rb") as f:
            source_bytes = f.read()

        import tree_sitter
        language_ptr = self.profile.get_language_ptr()
        try:
            lang = tree_sitter.Language(language_ptr)
        except Exception:
            lang = language_ptr
        parser = tree_sitter.Parser(lang)
        tree = parser.parse(source_bytes)

        # 2. Determine current navigation node
        current_start = target_info["start_byte"]
        current_end = target_info["end_byte"]

        if job.maps_state["node_history"]:
            current_start, current_end = job.maps_state["node_history"][-1]

        def find_node(node, start, end):
            if node.start_byte == start and node.end_byte == end:
                return node
            for child in node.children:
                if child.start_byte <= start and child.end_byte >= end:
                    res = find_node(child, start, end)
                    if res: return res
            return None

        current_node = find_node(tree.root_node, current_start, current_end)
        
        if not current_node:
            logger.error(f"[{self.name}] Could not find node at {current_start}-{current_end} in {filepath}")
            # Recovery: jump back up
            if job.maps_state["node_history"]:
                job.maps_state["node_history"].pop()
                return "MAPS", job
            else:
                job.maps_state["current_target_index"] += 1
                return "MAPS", job

        # 3. Render children
        children_view = []
        node_map = {} # id -> node
        
        for idx, child in enumerate(current_node.named_children):
            node_map[idx] = child
            rendered = self._render_node(source_bytes, child)
            children_view.append(f"[{idx}] {child.type}:\n{rendered}\n")

        children_view_str = "\n".join(children_view) if children_view else "(No named children)"

        logger.info(f"[{self.name}] Navigating {current_symbol} | Depth: {len(job.maps_state['node_history'])} | Node: {current_node.type}")

        error_context = ""
        if job.llm_feedback:
            error_context += f"PREVIOUS ERROR: {job.llm_feedback}\n\n"
        if hasattr(job, "test_stdout") and job.test_stdout:
            error_context += f"TEST FAILURE (Fix this error in your rewrite):\n{job.test_stdout}\n\n"

        variables = {
            "intent": job.intent,
            "error_context": error_context,
            "current_symbol": current_symbol,
            "current_node_type": current_node.type,
            "children_view": children_view_str,
        }

        system_prompt = self.config_manager.render_prompt(self.config.get("system_prompt", ""), variables)
        user_prompt = self.config_manager.render_prompt(self.config.get("user_prompt_template", ""), variables)

        status, response = self.llm.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": self.config.get("params", {}),
            "post_process": self.config.get("post_process")
        })

        if status != "SUCCESS":
            logger.error(f"[{self.name}] LLM generation failed: {response}")
            return "ABORT", job

        job.llm_feedback = "" # Clear previous feedback

        # 4. Handle LLM Action
        action = response.get("action")
        target_idx = response.get("target")
        code = response.get("code", "")

        logger.info(f"[{self.name}] LLM Action: {action} on target {target_idx}")

        if action == "zoom":
            if target_idx is not None and target_idx in node_map:
                target_node = node_map[target_idx]
                job.maps_state["node_history"].append((target_node.start_byte, target_node.end_byte))
            else:
                job.llm_feedback = f"Invalid target ID {target_idx} for zoom."
        elif action == "up":
            if job.maps_state["node_history"]:
                job.maps_state["node_history"].pop()
            else:
                job.llm_feedback = "Already at the top level of the extracted symbol."
        elif action in ["replace", "insert_before", "insert_after", "delete"]:
            if target_idx is not None and target_idx in node_map:
                target_node = node_map[target_idx]
                edit = {
                    "symbol": current_symbol,
                    "action": action,
                    "new_code": code
                }
                if action == "replace":
                    edit["start_byte"] = target_node.start_byte
                    edit["end_byte"] = target_node.end_byte
                elif action == "insert_before":
                    edit["start_byte"] = target_node.start_byte
                    edit["end_byte"] = target_node.start_byte
                elif action == "insert_after":
                    edit["start_byte"] = target_node.end_byte
                    edit["end_byte"] = target_node.end_byte
                elif action == "delete":
                    edit["start_byte"] = target_node.start_byte
                    edit["end_byte"] = target_node.end_byte
                    edit["new_code"] = "" # Empty code for delete
                    
                job.fixed_code["edits"].append(edit)
                logger.info(f"[{self.name}] Queued {action} edit at {edit['start_byte']}-{edit['end_byte']}")
                job.llm_feedback = f"Successfully queued {action} on node {target_idx}."
            else:
                job.llm_feedback = f"Invalid target ID {target_idx} for {action}."
        elif action == "done":
            job.maps_state["current_target_index"] += 1
            job.maps_state["node_history"] = [] # Reset history for next symbol
        else:
            job.llm_feedback = f"Unknown action: {action}"

        return "MAPS", job

class SYNTAX_GATE(State):
    """
    Validates all generated code snippets before they touch the disk.
    """
    def __init__(self, profile):
        super().__init__("SYNTAX_GATE")
        self.gate = SyntaxGate(profile.get_language_ptr())

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        logger.info(f"[{self.name}] Validating surgical ASTs...")

        if not isinstance(job.fixed_code, dict) or "edits" not in job.fixed_code:
            job.llm_feedback = "Response must be a JSON object with an 'edits' array."
            return "MAPS", job

        for edit in job.fixed_code["edits"]:
            result = self.gate.validate(edit["new_code"])
            if not result["valid"]:
                error_msg = result['error_message']
                symbol_name = edit.get('symbol', 'unknown')
                logger.error(f"[{self.name}] Syntax validation failed for {symbol_name}: {error_msg}")
                job.llm_feedback = f"Syntax error in {symbol_name}: {error_msg}"
                return "ROUTER", job

        job.llm_feedback = ""
        return "ACTUATE", job

class ACTUATE(State):
    """
    Splices all valid edits into the file in reverse byte-order.
    """
    def __init__(self):
        super().__init__("ACTUATE")
        self.splicer = ASTSplice()

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        if not job.extracted_nodes:
            logger.error(f"[{self.name}] No surgical target acquired! Aborting splice.")
            return "ABORT", job

        filepath = job.target_files[job.current_file_index]

        edits_to_apply = []
        provided_edits = job.fixed_code.get("edits", [])
        acquired_symbol_names = [n["symbol"] for n in job.extracted_nodes]

        for edit in provided_edits:
            symbol = edit.get("symbol")
            new_code = edit.get("new_code")
            node_data = next((n for n in job.extracted_nodes if n["symbol"] == symbol), None)
            if node_data:
                edits_to_apply.append({
                    "start_byte": node_data["start_byte"],
                    "end_byte": node_data["end_byte"],
                    "new_code": new_code
                })
            else:
                logger.warning(f"[{self.name}] LLM provided edit for symbol '{symbol}', but it was not in acquired list: {acquired_symbol_names}")

        if not edits_to_apply:
            logger.error(f"[{self.name}] No matching symbols found in edits! Provided: {[e.get('symbol') for e in provided_edits]}, Expected: {acquired_symbol_names}")
            job.llm_feedback = f"Error: You provided edits for symbols we didn't acquire. Only edit these: {acquired_symbol_names}"
            return "ROUTER", job

        logger.info(f"[{self.name}] Splicing {len(edits_to_apply)} nodes in {filepath}")

        status, result = self.splicer.tick({
            "filepath": filepath,
            "edits": edits_to_apply
        })

        if status == "SUCCESS":
            return "EVALUATE", job
        
        logger.error(f"[{self.name}] Splice failed: {result}")
        job.llm_feedback = f"Splice failed: {result}"
        return "ROUTER", job
