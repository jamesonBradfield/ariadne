import logging
import threading
import sys
import subprocess
import shlex
import pyperclip
import os
from datetime import datetime
from typing import Any, Dict, Optional, List, Callable, Union

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.live import Live
from rich.status import Status
from rich.table import Table

# Global Console instance pointing to raw stdout to avoid recursion loops
console = Console(file=sys.__stdout__)

class StateTransitionMessage:
    """Mock Textual message for engine compatibility."""
    def __init__(self, state_name: str, retry_count: int = 0) -> None:
        self.state_name = state_name
        self.retry_count = retry_count

class EngineLogMessage:
    def __init__(self, record: logging.LogRecord) -> None:
        self.record = record

class StdoutMessage:
    def __init__(self, text: str) -> None:
        self.text = text

class ChatUpdateMessage:
    def __init__(self, sender: str, content: str, style: str = "default") -> None:
        self.sender = sender
        self.content = content
        self.style = style

class EditorMessage:
    def __init__(self, command: str, completion_event: threading.Event) -> None:
        self.command = command
        self.completion_event = completion_event

class PromptUserMessage:
    def __init__(self, proposal: str, response_event: threading.Event, response_container: Dict[str, bool]) -> None:
        self.proposal = proposal
        self.response_event = response_event
        self.response_container = response_container

class TextualLogHandler(logging.Handler):
    def __init__(self, app: 'AriadneApp') -> None:
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        self.app.post_message(EngineLogMessage(record))

class RedirectOutput:
    """Redirects stdout/stderr to the app via messages."""
    def __init__(self, app: 'AriadneApp'):
        self.app = app

    def write(self, text: str):
        if text.strip():
            self.app.post_message(StdoutMessage(text))

    def flush(self):
        pass

class AriadneApp:
    """
    A professional, Aider-style interface using prompt-toolkit and rich.
    """
    def __init__(self, **kwargs):
        self.session = PromptSession()
        self.kb = KeyBindings()
        self.start_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self.engine_running = False
        self.current_prompt_event: Optional[threading.Event] = None
        self.current_prompt_container: Optional[Dict[str, bool]] = None
        
        # State tracking for display
        self.current_state = "IDLE"
        self.retry_count = 0
        self.active_intent = "None"
        self.targets: List[str] = []
        self.last_test_status: Optional[bool] = None

        # Setup custom styles for prompt-toolkit
        self.style = Style.from_dict({
            'prompt': '#7aa2f7 bold',
            'arrow': '#bb9af7',
        })

    def post_message(self, message: Any) -> None:
        """
        Mock of Textual's post_message. Routes messages to the appropriate handler method.
        Since we aren't in a full-screen app, we handle these in the main or engine thread.
        """
        if isinstance(message, StateTransitionMessage):
            self.on_state_transition_message(message)
        elif isinstance(message, EngineLogMessage):
            self.on_engine_log_message(message)
        elif isinstance(message, StdoutMessage):
            self.on_stdout_message(message)
        elif isinstance(message, PromptUserMessage):
            self.on_prompt_user_message(message)
        elif isinstance(message, EditorMessage):
            self.on_editor_message(message)
        elif isinstance(message, ChatUpdateMessage):
            self.on_chat_update_message(message)

    def run(self) -> None:
        """
        Main interactive loop using prompt-toolkit.
        """
        # Setup logging redirection
        handler = TextualLogHandler(self)
        logging.getLogger("ariadne").addHandler(handler)
        
        # Capture stdout/stderr with patch_stdout to not break the prompt
        redirector = RedirectOutput(self)
        sys.stdout = sys.stderr = redirector

        self.print_system_msg("Ariadne Engine Initialized. Type '/help' for commands.")
        
        with patch_stdout():
            while True:
                try:
                    # vi_mode=True enables Neovim-style navigation in the prompt
                    user_input = self.session.prompt(
                        "\n> ", 
                        vi_mode=True, 
                        style=self.style
                    ).strip()
                    
                    if not user_input:
                        continue
                        
                    if user_input.startswith("/"):
                        self.handle_command(user_input)
                        continue

                    if self.current_prompt_event:
                        # We are waiting for a user approval mid-engine
                        if user_input.lower() in ["y", "yes", "approve"]:
                            self.resolve_prompt(True)
                        elif user_input.lower() in ["n", "no", "reject"]:
                            self.resolve_prompt(False)
                        else:
                            self.print_system_msg("[bold red]Please reply with 'yes' or 'no' to approve the proposal.[/]")
                        continue

                    # Otherwise, it's a new intent
                    if not self.engine_running and self.start_callback:
                        self.engine_running = True
                        self.active_intent = user_input
                        self.print_ariadne_msg(f"Starting objective: {user_input}")
                        
                        threading.Thread(
                            target=self.start_callback, 
                            args=({"intent": user_input, "targets": self.targets},), 
                            daemon=True
                        ).start()
                    else:
                        self.print_system_msg("[yellow]Engine is already running. Please wait or use /stop (not yet implemented).[/]")

                except KeyboardInterrupt:
                    continue
                except EOFError:
                    self.print_system_msg("Shutting down...")
                    break
                except Exception as e:
                    self.print_system_msg(f"[bold red]Error in prompt: {e}[/]")

    def handle_command(self, cmd_text: str) -> None:
        parts = cmd_text.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "/exit":
            sys.exit(0)
        elif cmd == "/add":
            self.targets.extend(args)
            self.print_system_msg(f"Added targets: [cyan]{', '.join(args)}[/]")
        elif cmd == "/drop":
            self.targets = [t for t in self.targets if t not in args]
            self.print_system_msg(f"Dropped targets: [red]{', '.join(args)}[/]")
        elif cmd == "/clear":
            self.targets = []
            self.print_system_msg("Target list cleared.")
        elif cmd == "/stop":
            if self.engine_running and hasattr(self, "current_context"):
                self.current_context.stop_requested = True
                self.print_system_msg("Stop request sent to engine...")
            else:
                self.print_system_msg("No engine is currently running.")
        elif cmd == "/test":
            self.print_system_msg("Manual test execution not yet implemented via command.")
        elif cmd == "/ls":
            self.print_system_msg(f"Current targets: [cyan]{', '.join(self.targets) if self.targets else 'None'}[/]")
            self.print_system_msg(f"Active goal: [white]{self.active_intent}[/]")
        elif cmd == "/help":
            table = Table(title="[bold blue]Ariadne Commands[/]", show_header=True, header_style="bold magenta", border_style="cyan", box=None)
            table.add_column("Command", style="bold cyan", width=20)
            table.add_column("Description", style="white")
            
            table.add_row("/add <files>", "Add files to the surgical session")
            table.add_row("/drop <files>", "Remove files from the session")
            table.add_row("/clear", "Clear all targets")
            table.add_row("/ls", "List current targets and active goal")
            table.add_row("/stop", "Abort the current engine run")
            table.add_row("/exit", "Exit Ariadne")
            
            console.print(table)
            self.print_system_msg("Or simply type your coding objective to start the engine.")
        else:
            self.print_system_msg(f"[bold red]Unknown command: {cmd}[/]")

    def print_ariadne_msg(self, text: str, role: str = "Ariadne"):
        md = Markdown(text)
        panel = Panel(md, title=f"[bold blue]{role}[/bold blue]", border_style="blue", expand=False)
        console.print(panel)

    def print_system_msg(self, msg: str):
        console.print(f"[bold yellow]⚙️ {msg}[/bold yellow]")

    def on_engine_log_message(self, message: EngineLogMessage) -> None:
        msg = message.record.getMessage()
        if message.record.levelno >= logging.WARNING:
            color = "red" if message.record.levelno >= logging.ERROR else "yellow"
            console.print(f"[bold {color}] {msg}[/]")
        else:
            # Progress updates
            console.print(f"[dim] {msg}[/]")

    def on_stdout_message(self, message: StdoutMessage) -> None:
        content = message.text.strip()
        if content:
             console.print(f"[italic dim] {content}[/]")

    def on_chat_update_message(self, message: ChatUpdateMessage) -> None:
        self.print_ariadne_msg(message.content, role=message.sender)

    def on_state_transition_message(self, message: StateTransitionMessage) -> None:
        self.current_state = message.state_name
        self.retry_count = message.retry_count
        
        console.print(f"[dim] Transitioning to [bold magenta]{message.state_name}[/][/]")
        
        if message.state_name == "FINISH":
            self.engine_running = False
            self.print_system_msg("[bold green]Success! Task completed.[/]")

    def on_prompt_user_message(self, message: PromptUserMessage) -> None:
        self.current_prompt_event = message.response_event
        self.current_prompt_container = message.response_container
        
        proposal_text = f"**PROPOSAL REVIEW REQUIRED**\n\n{message.proposal}\n\nDo you approve this? (yes/no)"
        self.print_ariadne_msg(proposal_text)

    def resolve_prompt(self, approved: bool) -> None:
        if self.current_prompt_container and self.current_prompt_event:
            self.current_prompt_container["approved"] = approved
            self.current_prompt_event.set()
            self.current_prompt_event = None
            self.current_prompt_container = None
            self.print_system_msg("Approved. Continuing..." if approved else "Rejected.")

    def on_editor_message(self, message: EditorMessage) -> None:
        self.print_system_msg("Launching external editor...")
        # Since we use patch_stdout, we can just run the command
        try:
            subprocess.run(shlex.split(message.command))
        except Exception as e:
            logging.error(f"Failed to run editor: {e}")
        finally:
            message.completion_event.set()
        self.print_system_msg("Resuming...")

    # Compatibility methods for engine.py
    def update_intent(self, intent: str) -> None:
        self.active_intent = intent

    def update_files(self, files: List[str]) -> None:
        self.targets.extend(files)

    def update_test_status(self, success: bool, output: str) -> None:
        self.last_test_status = success
        status_str = "[bold green]PASSED[/]" if success else "[bold red]FAILED[/]"
        console.print(f" [bold]TEST STATUS:[/] {status_str}")

if __name__ == "__main__":
    AriadneApp().run()
