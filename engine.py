import argparse
import logging
import os
import json
import threading
import time
from typing import Any, Dict, List, Optional

from ariadne.core import EngineContext, State
from ariadne.payloads import JobPayload
from ariadne.states import (
    TRIAGE, DISPATCH, EVALUATE, THINKING, ROUTER, 
    SEARCH, SENSE, MAPS_NAV, MAPS_THINK, MAPS_SURGEON, SYNTAX_GATE, ACTUATE, 
    POST_MORTEM, INTERVENE
)
from ariadne.tui import AriadneApp, StateTransitionMessage

# Setup logging
def setup_logging(log_level="INFO", tui_mode=False):
    # Clear existing handlers
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        
    if not tui_mode:
        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    else:
        # Just set level, no handlers. TUI will add its own.
        logging.root.setLevel(getattr(logging, log_level.upper()))

logger = logging.getLogger("ariadne.core")


class ConfigManager:
    """
    Manages state-specific LLM configurations from a JSON file.
    """
    def __init__(self, config_path: str = "ariadne_config.json"):
        self.config = {
            "default": {
                "model": "openai/llama-cpp",
                "api_base": "http://localhost:8080/v1",
                "api_key": "none",
                "params": {
                    "temperature": 0.0,
                    "max_tokens": 4096
                }
            },
            "states": {}
        }
        
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    user_config = json.load(f)
                    # Deep merge defaults
                    if "default" in user_config:
                        for k, v in user_config["default"].items():
                            if k == "params" and isinstance(v, dict):
                                self.config["default"]["params"].update(v)
                            else:
                                self.config["default"][k] = v
                    if "states" in user_config:
                        self.config["states"].update(user_config["states"])
                    
                    # Merge editor config
                    if "editor" in user_config:
                        if "editor" not in self.config:
                            self.config["editor"] = {}
                        self.config["editor"].update(user_config["editor"])

                logger.info(f"Loaded LLM configuration from {config_path}")
            except Exception as e:
                logger.error(f"Failed to load config {config_path}: {e}. Using defaults.")

    def get_model_info(self, state_name: str) -> Dict[str, Any]:
        """
        Returns the merged model configuration for a specific state.
        """
        # Start with default
        info = json.loads(json.dumps(self.config["default"])) # Deep copy
        
        state_config = self.config["states"].get(state_name, {})
        
        # Merge state-specific config
        for k, v in state_config.items():
            if k == "params" and isinstance(v, dict):
                info["params"].update(v)
            else:
                info[k] = v
        return info

    @staticmethod
    def render_prompt(template: str, variables: Dict[str, Any]) -> str:
        """
        Simple {{variable}} substitution.
        """
        result = template
        for k, v in variables.items():
            result = result.replace(f"{{{{{k}}}}}", str(v))
        return result


class ProfileLoader:
    """
    Handles loading language profiles and expanding target lists.
    """
    @staticmethod
    def load_profile(name: str):
        if name.lower() == "rust":
            from ariadne.profiles.rust_profile import RustProfile
            return RustProfile()
        elif name.lower() == "python":
            from ariadne.profiles.python_profile import PythonProfile
            return PythonProfile()
        else:
            raise ValueError(f"Unsupported profile: {name}")

    @staticmethod
    def expand_targets(targets: List[str], profile) -> List[str]:
        expanded = []
        ignore_handler = IgnoreHandler()
        for t in targets:
            if os.path.isfile(t):
                expanded.append(t)
            elif os.path.isdir(t):
                for root, dirs, files in os.walk(t):
                    # Prune ignored directories in-place
                    dirs[:] = [d for d in dirs if not ignore_handler.is_ignored(os.path.join(root, d))]
                    
                    for f in files:
                        full_path = os.path.join(root, f)
                        if any(full_path.endswith(ext) for ext in profile.extensions):
                            if not ignore_handler.is_ignored(full_path):
                                expanded.append(full_path)
        return expanded


class IgnoreHandler:
    """
    Handles .ariadneignore and .gitignore logic.
    """
    def __init__(self):
        self.ignore_patterns = [".venv", "target", ".git", "__pycache__", ".ruff_cache"]
        if os.path.exists(".ariadneignore"):
            with open(".ariadneignore", "r") as f:
                self.ignore_patterns.extend([line.strip() for line in f if line.strip() and not line.startswith("#")])

    def is_ignored(self, path: str) -> bool:
        return any(pattern in path for pattern in self.ignore_patterns)


def run_engine_loop(context: EngineContext, states_registry: Dict[str, State], initial_payload: Any, app: Optional[AriadneApp] = None):
    """
    Executes the HFSM loop. Can be run in a background thread.
    """
    payload = initial_payload
    
    if app:
        intent = getattr(payload, "intent", payload.get("intent", "")) if payload else ""
        app.call_from_thread(app.update_intent, intent)

    start_wall_time = time.time()
    turn_count = 0
    
    # Defaults
    max_turns = 20
    global_timeout = 1800
    
    try:
        import __main__
        if hasattr(__main__, 'args'):
            max_turns = getattr(__main__.args, 'max_turns', 20)
            global_timeout = getattr(__main__.args, 'timeout', 1800)
    except Exception:
        pass

    while context.current_state != "FINISH":
        # Safety Checks
        elapsed_total = time.time() - start_wall_time
        if elapsed_total > global_timeout:
            logger.error(f"Global timeout reached ({global_timeout}s). Aborting.")
            context.transition("ABORT")
            # Continue to allow one last tick to POST_MORTEM if needed
        
        if turn_count >= max_turns and context.current_state not in ["SUCCESS", "ABORT", "POST_MORTEM"]:
            logger.error(f"Maximum transitions reached ({max_turns}). Aborting.")
            context.transition("ABORT")

        logger.info(f"--- TICKING: {context.current_state} (Turn {turn_count+1}, {int(elapsed_total)}s) ---")
        
        # Terminal states transition to POST_MORTEM
        if context.current_state in ["SUCCESS", "ABORT"]:
             context.transition("POST_MORTEM")
             logger.info(f"Terminal state {context.current_state} reached. Transitioning to POST_MORTEM.")

        if app:
            # retry_count = getattr(payload, "retry_count", 0) if hasattr(payload, "retry_count") else 0
            # Use global turn count for TUI indicator
            app.post_message(StateTransitionMessage(context.current_state, turn_count + 1))
            
            # Update Plan tab if plan changed
            if hasattr(payload, "plan") and payload.plan:
                app.call_from_thread(app.update_plan, payload.plan)
            
            # Update Surgeon tab if MAPS has extracted nodes
            if hasattr(payload, "extracted_nodes") and payload.extracted_nodes:
                # Show the currently active node being worked on by MAPS
                idx = getattr(payload, "maps_state", {}).get("current_target_index", 0)
                if idx < len(payload.extracted_nodes):
                    node = payload.extracted_nodes[idx]
                    # ROBUST FIX: Ensure payload.fixed_code exists and is NOT None
                    edits = []
                    if hasattr(payload, "fixed_code") and payload.fixed_code is not None:
                        edits = payload.fixed_code.get("edits", [])
                    app.call_from_thread(app.update_surgeon, node["symbol"], node["node_string"], edits)

        active_state = states_registry.get(context.current_state)
        
        if not active_state:
            logger.error(f"State {context.current_state} not found!")
            break

        start_time = time.time()
        
        current_state_name, payload = active_state.tick(payload)
        
        elapsed = time.time() - start_time
        logger.info(f"[BENCHMARK] {context.current_state} took {elapsed:.2f}s")
        
        context.transition(current_state_name)
        turn_count += 1

        if context.stop_requested:
            logger.warning("Stop requested by user. Transitioning to ABORT.")
            context.transition("ABORT")

        if current_state_name == "FINISH":
             break
             
    if app:
        app.post_message(StateTransitionMessage("FINISH", 0))

    logger.info(f"Engine dropped to terminal state: {context.current_state}")


def main():
    parser = argparse.ArgumentParser(description="Ariadne ECU: Surgical Code Repair Engine")
    parser.add_argument("--targets", nargs="+", help="Files or directories to ingest")
    parser.add_argument("--profile", default="rust", help="Language profile to use")
    parser.add_argument("--config", default="ariadne_config.json", help="Path to LLM configuration JSON")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--intent", default="Implement armor mitigation and death state in take_damage method.", help="The user request or coding intent")
    parser.add_argument("--initial-state", default="INTERVENE", help="The starting state for the engine")
    parser.add_argument("--tui", action="store_true", help="Enable the Textual Dashboard TUI")
    parser.add_argument("--headless", action="store_true", help="Run without interactive editor interventions")
    parser.add_argument("--project-dir", "-C", default=".", help="Set the project working directory")
    parser.add_argument("--max-turns", type=int, default=20, help="Maximum transitions before aborting")
    parser.add_argument("--timeout", type=int, default=1800, help="Global timeout in seconds")
    args = parser.parse_args()

    setup_logging(args.log_level, args.tui)

    # Resolve config path before changing directory
    config_path = os.path.abspath(args.config)
    
    # Absolute-ize targets before chdir so we can resolve them cleanly against the new root
    if args.targets:
        abs_targets = [os.path.abspath(t) for t in args.targets]
    else:
        abs_targets = None

    if args.project_dir and args.project_dir != ".":
        os.chdir(args.project_dir)
        logging.getLogger("ariadne").info(f"Changed project working directory to: {args.project_dir}")
        
    # Convert targets to be relative to the new working directory
    if abs_targets:
        args.targets = [os.path.relpath(t, os.getcwd()) for t in abs_targets]

    # 1. Load Configuration and Profile
    config_manager = ConfigManager(config_path)
    profile = ProfileLoader.load_profile(args.profile)
    
    # Inject headless arg into config
    if "editor" not in config_manager.config:
        config_manager.config["editor"] = {}
    config_manager.config["editor"]["headless"] = args.headless

    # 2. Expand Targets (Allow empty if TUI is coming)
    target_files = ProfileLoader.expand_targets(args.targets or ["."], profile)
    if not target_files and not args.tui:
        logger.critical("No target files found! Check your --targets or .ariadneignore.")
        return

    if target_files:
        logger.info(f"Loaded {profile.name} profile with {len(target_files)} files.")
    else:
        logger.info(f"Loaded {profile.name} profile. Waiting for targets in TUI...")

    # 3. Registry Creation Helper
    def create_states(target_files_list: List[str]):
        engine_root = os.path.dirname(os.path.abspath(__file__))
        rust_test_script = os.path.join(engine_root, "scripts", "run_rust_tests.py")
        python_test_script = os.path.join(engine_root, "scripts", "run_python_tests.py")

        return {
            "TRIAGE": TRIAGE(config_manager),
            "DISPATCH": DISPATCH(
                config_manager, 
                test_filepath=f"test_contract{profile.extensions[0]}", 
                profile=profile,
                target_files=target_files_list
            ),
            "EVALUATE": EVALUATE(
                test_command=f"python {rust_test_script} {target_files_list[0]} test_contract{profile.extensions[0]}" 
                if target_files_list and profile.name == "Rust" else 
                f"python {python_test_script} {target_files_list[0]} test_contract{profile.extensions[0]}"
                if target_files_list else "echo No targets provided"
            ),
            "THINKING": THINKING(config_manager, profile),
            "ROUTER": ROUTER(config_manager),
            "SEARCH": SEARCH(config_manager, profile),

            "SENSE": SENSE(profile),
            "MAPS_NAV": MAPS_NAV(config_manager, profile),
            "MAPS_THINK": MAPS_THINK(config_manager, profile),
            "MAPS_SURGEON": MAPS_SURGEON(config_manager, profile),
            "SYNTAX_GATE": SYNTAX_GATE(profile),
            "ACTUATE": ACTUATE(),
            "POST_MORTEM": POST_MORTEM(config_manager),
            "INTERVENE": INTERVENE(config_manager),
        }

    states_registry = create_states(target_files)

    # 4. Initialize Engine Context
    context = EngineContext(initial_state=args.initial_state.upper())
    
    if context.current_state == "TRIAGE":
        payload = {"input": args.intent, "target_files": target_files}
    elif context.current_state == "INTERVENE":
        payload = {
            "intent": args.intent, 
            "target_files": target_files, 
            "needs_elaboration": True, 
            "next_headless_state": "TRIAGE"
        }
    else:
        # If bypassing TRIAGE/DISPATCH, mock the payload structure they would have created
        payload = JobPayload(intent=args.intent, target_files=target_files)

    # 5. Launch UI or CLI Loop
    if args.tui:
        app = AriadneApp()
        
        def start_engine_callback(setup_data: Dict[str, Any]):
            nonlocal target_files, states_registry, payload
            
            new_intent = setup_data.get("intent", args.intent)
            new_targets_raw = setup_data.get("targets", "")
            
            # If targets were passed as a list from chat /add command
            if isinstance(new_targets_raw, list):
                target_files = ProfileLoader.expand_targets(new_targets_raw, profile)
            elif isinstance(new_targets_raw, str) and new_targets_raw.strip():
                new_targets_list = [t.strip() for t in new_targets_raw.split(",") if t.strip()]
                target_files = ProfileLoader.expand_targets(new_targets_list, profile)
            
            # Re-build states
            states_registry = create_states(target_files)
            
            # INTELLIGENT SKIP: If intent is already substantial, skip elaboration
            start_state = "TRIAGE" if len(new_intent) > 15 else "INTERVENE"
            context.transition(start_state)

            current_payload = None
            if start_state == "TRIAGE":
                current_payload = {"input": new_intent, "target_files": target_files, "app": app}
            else:
                current_payload = {
                    "intent": new_intent, 
                    "target_files": target_files, 
                    "needs_elaboration": True, 
                    "next_headless_state": "TRIAGE",
                    "app": app
                }
            
            # Update all states with app for UI messages
            for state_obj in states_registry.values():
                if hasattr(state_obj, "prompt_user"):
                    state_obj.prompt_user.app = app

            # Provide context to app for /stop slash command
            app.current_context = context

            engine_thread = threading.Thread(
                target=run_engine_loop,
                args=(context, states_registry, current_payload, app),
                daemon=True
            )
            engine_thread.start()

        app.start_callback = start_engine_callback
        app.initial_setup_data = {
            "intent": args.intent,
            "targets": ", ".join(args.targets) if args.targets else ""
        }
        
        app.run()
    else:
        run_engine_loop(context, states_registry, payload)


if __name__ == "__main__":
    main()
