import logging
from typing import Any, Tuple, Dict, List
from core import State
from payloads import ContextPayload, JobPayload
from primitives import ExtractAST, QueryLLM, ExecuteCommand, PromptUser, WriteFile

logger = logging.getLogger("ariadne.parent_states")

class TRIAGE(State):
    """
    Initializes ContextPayload and determines user intent.
    """
    def __init__(self, model_info: Dict[str, Any]):
        super().__init__("TRIAGE")
        self.query_llm = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))

    def tick(self, payload: Any) -> Tuple[str, Any]:
        # Support both raw string and dict-based payload for flexibility
        if isinstance(payload, dict):
            raw_input = payload.get("input", "")
        else:
            raw_input = payload
            
        context = ContextPayload(
            raw_prompt=raw_input,
            live_runtime_data=None,
            project_skeleton=""
        )
        
        system_prompt = "You are a triage agent. Extract the core technical intent from the user request. Output ONLY the intent."
        status, intent = self.query_llm.tick({
            "system": system_prompt,
            "user": context.raw_prompt
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
    def __init__(self, model_info: Dict[str, Any], test_filepath: str, profile: Any, target_files: List[str] = None):
        super().__init__("DISPATCH")
        self.test_filepath = test_filepath
        self.target_files = target_files or []
        self.profile = profile
        self.extractor = ExtractAST(profile.get_language_ptr())
        self.skeleton_query = profile.get_skeleton_query()
        self.query_llm = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
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
        logger.debug(f"[DISPATCH] Skeleton Context (API Surface):\n{skeleton_context}")
        
        # 2. Generate Test
        system_prompt = self.profile.test_generation_system_prompt
        user_prompt = f"Intent: {intent}\n\n{self.profile.name} API Surface:\n{skeleton_context}"
        
        status, test_code = self.query_llm.tick({
            "system": system_prompt,
            "user": user_prompt
        })
        
        # 3. Prompt for Approval
        p_status, approved = self.prompt_user.tick(f"Proposed Test:\n{test_code}")
        
        if not approved:
            return "HALT", job
            
        # 3. Save Test
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
            logger.warning("Tests failed. Transitioning to SEARCH.")
            job.test_stdout = output
            job.retry_count += 1
            return "SEARCH", job

class SEARCH(State):
    """
    Identifies and extracts relevant code context.
    """
    def __init__(self, model_info: Dict[str, Any], profile: Any, node_query_template: str):
        super().__init__("SEARCH")
        self.profile = profile
        self.extractor = ExtractAST(profile.get_language_ptr())
        self.query_llm = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        self.skeleton_query = profile.get_skeleton_query()
        self.node_query_template = node_query_template

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        # 1. Get skeletons for all target files
        all_skeletons = []
        for filepath in job.target_files:
            status, skeletons = self.extractor.tick({
                "filepath": filepath,
                "query_string": self.skeleton_query,
                "capture_name": self.profile.skeleton_capture_name
            })
            all_skeletons.extend(skeletons)
            
        # 2. Identify missing nodes
        system_prompt = "Identify the specific function or struct names needed to satisfy the test error."
        status, needed_nodes = self.query_llm.tick({
            "system": system_prompt,
            "user": f"Error: {job.test_stdout}\nSkeletons: {' '.join(all_skeletons)}",
            "schema": {"nodes": ["list of strings"]}
        })
        
        # 3. Extract full code for identified nodes
        # Clear previous context for amnesia-tick style isolation
        job.extracted_context = []
        
        if isinstance(needed_nodes, dict) and "nodes" in needed_nodes:
            for node_name in needed_nodes["nodes"]:
                status, full_code_list = self.extractor.tick({
                    "filepath": job.target_files[0],
                    "query_string": self.node_query_template.format(node_name=node_name),
                    "capture_name": "node"
                })
                if status == "SUCCESS":
                    job.extracted_context.extend(full_code_list)
                    logger.info(f"Extracted node: {node_name}")
                
        return "CODING", job

class CODING(State):
    """
    Rewrites code to fix the test and triggers Amnesia Tick.
    """
    def __init__(self, model_info: Dict[str, Any]):
        super().__init__("CODING")
        self.query_llm = QueryLLM(model=model_info.get("model"), api_base=model_info.get("api_base"))
        self.write_file = WriteFile()

    def tick(self, job: JobPayload) -> Tuple[str, JobPayload]:
        # 1. Generate Fix
        system_prompt = "Provide the full updated implementation for the file. RAW CODE ONLY."
        context_str = "\n".join(job.extracted_context)
        user_prompt = f"Intent: {job.intent}\nError: {job.test_stdout}\nContext:\n{context_str}"
        
        status, fixed_code = self.query_llm.tick({
            "system": system_prompt,
            "user": user_prompt
        })
        
        # 2. Overwrite file
        # Assuming the first target file for this MVP
        self.write_file.tick({
            "filepath": job.target_files[0],
            "content": fixed_code
        })
        
        logger.info("Code rewritten. Triggering Amnesia Tick (Resetting LLM context).")
        # In this architecture, returning to EVALUATE and wiping local state is the amnesia tick.
        return "EVALUATE", job
