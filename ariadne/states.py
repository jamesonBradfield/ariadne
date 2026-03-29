import logging
from typing import Any, Tuple, Dict, List
from .core import State
from .payloads import JobPayload
from .primitives import ExtractAST, QueryLLM, ExecuteCommand, PromptUser, WriteFile, ASTSplice
from .components import TreeSitterSensor, SyntaxGate

logger = logging.getLogger("ariadne.parent_states")

class DISPATCH(State):
    """
    EXECUTION: Generates a test contract to define the failure state.
    Queries LLM.
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

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        # 1. Get Skeleton for context
        all_skeletons = []
        for filepath in job.target_files:
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
            "intent": job.intent,
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
    PERCEPTION: Runs tests and captures environment state (stdout/stderr/compiler output).
    Does NOT query LLM.
    """
    def __init__(self, test_command: str = "cargo test"):
        super().__init__("EVALUATE")
        self.test_command = test_command
        self.executor = ExecuteCommand()

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        # Sensor: Get current state of the world
        status, output = self.executor.tick(self.test_command)
        job.test_stdout = output
        
        # If we are in the initial setup, go to TRIAGE
        if not job.intent:
            return "TRIAGE", job
            
        # Otherwise, return to the Root (THINKING) to evaluate progress
        return "THINKING", job

class TRIAGE(State):
    """
    REASONING: Distills user input + environment state into a technical intent.
    Queries LLM.
    """
    def __init__(self, config_manager: Any):
        super().__init__("TRIAGE")
        self.config_manager = config_manager
        self.config = config_manager.get_model_info("TRIAGE")
        self.query_llm = QueryLLM(model=self.config.get("model"), api_base=self.config.get("api_base"))

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        # Merge raw input (if any) with perception data from EVALUATE
        variables = {
            "input": job.input or "None provided",
            "environment_state": job.test_stdout or "Unknown"
        }
        
        system_prompt = self.config_manager.render_prompt(self.config.get("system_prompt", ""), variables)
        user_prompt = self.config_manager.render_prompt(self.config.get("user_prompt_template", ""), variables)

        status, intent = self.query_llm.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": self.config.get("params", {}),
            "post_process": self.config.get("post_process")
        })
        
        if status != "SUCCESS":
            return "ERROR", job
            
        job.intent = intent
        # Triage completed: Proceed to high-level Planning
        return "THINKING", job

class THINKING(State):
    """
    STRATEGIC ARCHITECT (ROOT): Analyzes the current state and Distilled Intent to decide the next step.
    Orchestrates transitions between SENSE, DISPATCH, and EVALUATE.
    """
    def __init__(self, config_manager: Any, profile: Any):
        super().__init__("THINKING")
        self.config_manager = config_manager
        self.profile = profile
        self.config = config_manager.get_model_info("THINKING")
        self.query_llm = QueryLLM(model=self.config.get("model"), api_base=self.config.get("api_base"))
        self.extractor = ExtractAST(profile.get_language_ptr())

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        # 1. Perception Check: Gather symbols from target files
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
                name_match = re.search(r"(?:pub\s+)?(?:fn|struct|class|impl|enum|trait)\s+(\w+)", s)
                if name_match:
                    available_symbols.append(name_match.group(1))
                all_skeletons.append(s)

        # 2. Planning: Use LLM to decide the next high-level action
        # Compress available symbols to keep context window small
        sym_summary = ", ".join(set(available_symbols))
        if len(sym_summary) > 200:
            sym_summary = sym_summary[:200] + "... [TRUNCATED]"

        variables = {
            "intent": job.intent[:500], # Don't let intent bloat
            "available_symbols": sym_summary,
            "test_stdout": job.test_stdout[:500] if job.test_stdout else "No errors yet.",
            "retry_count": job.retry_count,
            "has_test": "Yes" if job.read_only_tests else "No"
        }
        
        system_prompt = self.config_manager.render_prompt(
            "You are the Master Planner. Your goal is to satisfy the Intent. "
            "Available Actions:\n"
            "- DISPATCH: Generate a new test if one is missing or incorrect.\n"
            "- SEARCH: If we have a test failure and know what to fix.\n"
            "- SUCCESS: If intent is satisfied and tests pass.\n"
            "Output RAW JSON: {\"action\": \"...\", \"reasoning\": \"...\", \"steps\": [{\"symbol\": \"...\"}]}",
            variables
        )
        user_prompt = self.config_manager.render_prompt(
            "Intent: {{intent}}\nErrors: {{test_stdout}}\nHas Test: {{has_test}}\nSymbols: {{available_symbols}}", 
            variables
        )

        status, plan = self.query_llm.tick({
            "system": system_prompt,
            "user": user_prompt,
            "params": {"max_tokens": 512},
            "post_process": "extract_json"
        })

        if status == "SUCCESS" and isinstance(plan, dict):
            job.plan = plan
            action = plan.get("action", "ABORT").upper()
            logger.info(f"[{self.name}] Strategic Decision: {action} - {plan.get('reasoning')}")
            
            if action == "SEARCH":
                # Populate target_symbols for SENSE
                job.target_symbols = [step["symbol"] for step in plan.get("steps", []) if "symbol" in step]
                return "SEARCH", job
            
            return action, job
        
        logger.error(f"[{self.name}] Planning failed.")
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

        return "CODING", job

class CODING(State):
    """
    Uses LLM to rewrite the acquired AST nodes via strict JSON schema.
    """
    def __init__(self, config_manager: Any, profile: Any):
        super().__init__("CODING")
        self.config_manager = config_manager
        self.config = config_manager.get_model_info("CODING")
        self.llm = QueryLLM(model=self.config.get("model"), api_base=self.config.get("api_base"))
        self.profile = profile

    def tick(self, job: JobPayload) -> Tuple[str, Any]:
        if not job.extracted_nodes:
            return "SENSE", job

        logger.info(f"[{self.name}] --- AMNESIC TICK: Fresh LLM Context for {job.target_files[job.current_file_index]} ---")

        error_context = ""
        if job.llm_feedback:
            error_context += f"PREVIOUS ERROR: {job.llm_feedback}\n\n"
        if hasattr(job, "test_stdout") and job.test_stdout:
            error_context += f"TEST FAILURE (Fix this error in your rewrite):\n{job.test_stdout}\n\n"

        context_str = ""
        acquired_symbols = []
        for node in job.extracted_nodes:
            acquired_symbols.append(node['symbol'])
            context_str += f"--- Symbol: {node['symbol']} ---\n{node['node_string']}\n\n"

        variables = {
            "language": self.profile.name,
            "intent": job.intent,
            "error_context": error_context,
            "context_str": context_str,
            "acquired_symbols": ", ".join(acquired_symbols),
            "coding_example": self.profile.coding_example
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

        job.fixed_code = response  # Now a dictionary with 'edits'
        return "SYNTAX_GATE", job

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
            return "CODING", job

        for edit in job.fixed_code["edits"]:
            result = self.gate.validate(edit["new_code"])
            if not result["valid"]:
                error_msg = result['error_message']
                symbol_name = edit.get('symbol', 'unknown')
                logger.error(f"[{self.name}] Syntax validation failed for {symbol_name}: {error_msg}")
                job.llm_feedback = f"Syntax error in {symbol_name}: {error_msg}"
                return "CODING", job

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
            return "CODING", job

        logger.info(f"[{self.name}] Splicing {len(edits_to_apply)} nodes in {filepath}")

        status, result = self.splicer.tick({
            "filepath": filepath,
            "edits": edits_to_apply
        })

        if status == "SUCCESS":
            return "EVALUATE", job
        
        logger.error(f"[{self.name}] Splice failed: {result}")
        return "ABORT", job
