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
            return "SEARCH", job
        
        logger.error(f"[{self.name}] Failed to generate logical plan. Status: {status}, Plan Type: {type(plan)}")
        if status != "SUCCESS":
             logger.error(f"[{self.name}] LLM Error Details: {plan}")
        else:
             logger.error(f"[{self.name}] Non-dict plan received. Raw content (truncated): {str(plan)[:500]}")
             
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
