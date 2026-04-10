import logging
import threading
import sys
import subprocess
import shlex
import pyperclip
from datetime import datetime
from typing import Any, Dict, Optional, List, Callable, Union

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, Static, RichLog, Input, Label, ListItem, ListView
from textual.reactive import reactive
from textual.message import Message
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.theme import Theme

# Custom Theme inspired by Aider/Tokyonight
TokyonightTheme = Theme(
    name="tokyonight",
    primary="#7aa2f7",
    secondary="#bb9af7",
    accent="#ff9e64",
    foreground="#a9b1d6",
    background="#1a1b26",
    success="#9ece6a",
    warning="#e0af68",
    error="#f7768e",
    surface="#24283b",
)

class StateTransitionMessage(Message):
    """Sent when the engine transitions to a new state."""
    def __init__(self, state_name: str, retry_count: int = 0) -> None:
        self.state_name = state_name
        self.retry_count = retry_count
        super().__init__()

class EngineLogMessage(Message):
    """Sent to log a message in the TUI."""
    def __init__(self, record: logging.LogRecord) -> None:
        self.record = record
        super().__init__()

class StdoutMessage(Message):
    """Sent to log raw stdout/stderr in the TUI."""
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()

class ChatUpdateMessage(Message):
    """Sent to add a message to the chat history."""
    def __init__(self, sender: str, content: str, style: str = "default") -> None:
        self.sender = sender
        self.content = content
        self.style = style
        super().__init__()

class EditorMessage(Message):
    """Sent to request an external editor launch."""
    def __init__(self, command: str, completion_event: threading.Event) -> None:
        self.command = command
        self.completion_event = completion_event
        super().__init__()

class PromptUserMessage(Message):
    """Sent to request user approval for a proposal."""
    def __init__(self, proposal: str, response_event: threading.Event, response_container: Dict[str, bool]) -> None:
        self.proposal = proposal
        self.response_event = response_event
        self.response_container = response_container
        super().__init__()

class ChatMessage(Static):
    """A single message in the chat history."""
    def __init__(self, sender: str, content: str, style: str = "default"):
        super().__init__()
        self.sender = sender
        self.content = content
        self.msg_style = style

    def render(self) -> str:
        colors = {
            "user": "bold cyan",
            "ariadne": "bold blue",
            "engine": "dim white",
            "error": "bold red",
            "success": "bold green",
            "lsp": "bold magenta"
        }
        color = colors.get(self.sender.lower(), "white")
        prefix = f"[{color}]{self.sender.upper()}[/]"
        return f"{prefix}\n{self.content}\n"

class RedirectOutput:
    """Redirects stdout/stderr to the Textual app via messages."""
    def __init__(self, app: App):
        self.app = app

    def write(self, text: str):
        if text.strip():
            self.app.post_message(StdoutMessage(text))

    def flush(self):
        pass

class TextualLogHandler(logging.Handler):
    def __init__(self, app: App) -> None:
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        self.app.post_message(EngineLogMessage(record))

class EngineStatus(Static):
    state_name = reactive("IDLE")
    retry_count = reactive(0)
    start_time = datetime.now()

    def render(self) -> str:
        elapsed = datetime.now() - self.start_time
        return (
            f"[bold blue]STATE:[/] [green]{self.state_name}[/] | "
            f"[bold blue]RETRY:[/] [yellow]{self.retry_count}[/] | "
            f"[bold blue]TIME:[/] {str(elapsed).split('.')[0]}"
        )

class AriadneApp(App):
    """
    An interactive, chat-centric Ariadne interface.
    """
    CSS = """
    AriadneApp {
        background: #1a1b26;
        color: #a9b1d6;
    }

    #chat-container {
        height: 1fr;
        padding: 1 2;
        background: #1a1b26;
    }

    #chat-log {
        height: 1fr;
        border: none;
        background: #1a1b26;
    }

    #input-container {
        height: 3;
        dock: bottom;
        background: #24283b;
        border-top: solid #414868;
        padding: 0 1;
    }

    #main-input {
        background: #24283b;
        border: none;
        color: #c0caf5;
    }

    #sidebar {
        width: 35;
        dock: right;
        background: #1f2335;
        border-left: solid #414868;
        padding: 1;
    }

    .sidebar-section {
        margin-bottom: 1;
        padding: 1;
        background: #24283b;
        border: solid #414868;
    }

    .sidebar-title {
        color: #7aa2f7;
        text-style: bold;
        margin-bottom: 1;
    }

    #status-bar {
        height: 1;
        dock: top;
        background: #24283b;
        color: #7aa2f7;
        padding: 0 1;
    }

    ChatMessage {
        margin-bottom: 1;
        padding: 0 1;
    }

    .user-msg { color: #7aa2f7; }
    .ariadne-msg { color: #bb9af7; }
    .engine-msg { color: #565f89; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("ctrl+l", "clear_chat", "Clear"),
        Binding("f1", "help", "Help"),
    ]

    engine_running = reactive(False)
    current_intent = reactive("None")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.start_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self.current_prompt_event: Optional[threading.Event] = None
        self.current_prompt_container: Optional[Dict[str, bool]] = None
        self.chat_history: List[Dict[str, str]] = []

    def compose(self) -> ComposeResult:
        yield EngineStatus(id="status-bar")
        with Horizontal():
            with Vertical(id="chat-container"):
                yield RichLog(id="chat-log", wrap=True, highlight=True, markup=True)
                with Horizontal(id="input-container"):
                    yield Label("[bold cyan]>[/] ", id="prompt-label")
                    yield Input(placeholder="Ask Ariadne or type a slash command...", id="main-input")
            with Vertical(id="sidebar"):
                with Vertical(class_="sidebar-section"):
                    yield Label("ACTIVE GOAL", class_="sidebar-title")
                    yield Static("No active objective.", id="intent-display")
                with Vertical(class_="sidebar-section"):
                    yield Label("FILES IN CHAT", class_="sidebar-title")
                    yield Static("None", id="files-display")
                with Vertical(class_="sidebar-section"):
                    yield Label("LAST TEST", class_="sidebar-title")
                    yield Static("Waiting...", id="test-display")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "ARIADNE Surgical Engine"
        handler = TextualLogHandler(self)
        logging.getLogger("ariadne").addHandler(handler)
        
        # Capture stdout/stderr
        redirector = RedirectOutput(self)
        sys.stdout = sys.stderr = redirector

        self.add_chat_message("ariadne", "Hello! I am Ariadne, your surgical code repair engine. How can I help you today?")
        self.query_one("#main-input", Input).focus()

    def add_chat_message(self, sender: str, content: str, style: str = "default") -> None:
        log = self.query_one("#chat-log", RichLog)
        
        colors = {
            "user": "#7aa2f7",
            "ariadne": "#bb9af7",
            "engine": "#565f89",
            "error": "#f7768e",
            "success": "#9ece6a",
            "lsp": "#bb9af7"
        }
        color = colors.get(sender.lower(), "#a9b1d6")
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{color} bold]{sender.upper()}[/] [dim]{timestamp}[/]"
        
        log.write(f"{prefix}")
        log.write(content)
        log.write("") # Spacer

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return

        self.add_chat_message("user", text)
        event.input.value = ""

        if text.startswith("/"):
            await self.handle_command(text)
        else:
            if not self.engine_running and self.start_callback:
                self.engine_running = True
                self.update_intent(text)
                # Pass targets from our internal tracked list
                targets = self.query_one("#files-display", Static).renderable
                targets_list = []
                if targets and targets != "None":
                    targets_list = str(targets).split("\n")
                
                # We start the engine in a separate thread to keep TUI responsive
                threading.Thread(target=self.start_callback, args=({"intent": text, "targets": targets_list},), daemon=True).start()
            elif self.current_prompt_event:
                # User is responding to a prompt
                if text.lower() in ["y", "yes", "approve"]:
                    self.resolve_prompt(True)
                elif text.lower() in ["n", "no", "reject"]:
                    self.resolve_prompt(False)
                else:
                    self.add_chat_message("ariadne", "Please reply with [bold]yes[/] or [bold]no[/] to approve the proposal.")

    async def handle_command(self, cmd_text: str) -> None:
        parts = cmd_text.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "/quit":
            self.exit()
        elif cmd == "/clear":
            self.query_one("#chat-log", RichLog).clear()
        elif cmd == "/add":
            self.add_chat_message("ariadne", f"Added files to session: {', '.join(args)}")
            self.update_files(args)
        elif cmd == "/help":
            help_text = (
                "[bold cyan]/add <files>[/] - Add files to the surgical session\n"
                "[bold cyan]/clear[/]       - Clear the chat history\n"
                "[bold cyan]/quit[/]        - Exit Ariadne\n"
                "Or simply type your coding objective to start the engine."
            )
            self.add_chat_message("ariadne", help_text)
        else:
            self.add_chat_message("error", f"Unknown command: {cmd}")

    def on_engine_log_message(self, message: EngineLogMessage) -> None:
        # Filter noisy logs, only show relevant ones in chat if needed
        # For now, let's keep chat clean and maybe put logs in a separate view or dim them
        msg = message.record.getMessage()
        if message.record.levelno >= logging.WARNING:
            self.add_chat_message("error" if message.record.levelno >= logging.ERROR else "engine", msg)
        else:
            # Subtle engine progress updates
            self.add_chat_message("engine", f"[dim]{msg}[/]")

    def on_stdout_message(self, message: StdoutMessage) -> None:
        content = message.text.strip()
        if content:
             self.add_chat_message("engine", f"[italic dim]{content}[/]")

    def on_state_transition_message(self, message: StateTransitionMessage) -> None:
        status = self.query_one("#status-bar", EngineStatus)
        status.state_name = message.state_name
        status.retry_count = message.retry_count
        
        self.add_chat_message("ariadne", f"Transitioning to [bold magenta]{message.state_name}[/]")
        
        if message.state_name == "FINISH":
            self.engine_running = False
            self.add_chat_message("success", "Task completed successfully!")

    def on_prompt_user_message(self, message: PromptUserMessage) -> None:
        self.current_prompt_event = message.response_event
        self.current_prompt_container = message.response_container
        
        prompt_text = (
            f"[bold yellow]PROPOSAL REVIEW REQUIRED[/]\n\n"
            f"{message.proposal}\n\n"
            f"Do you approve this? ([bold green]yes[/]/[bold red]no[/])"
        )
        self.add_chat_message("ariadne", prompt_text)

    def resolve_prompt(self, approved: bool) -> None:
        if self.current_prompt_container and self.current_prompt_event:
            self.current_prompt_container["approved"] = approved
            self.current_prompt_event.set()
            self.current_prompt_event = None
            self.current_prompt_container = None
            self.add_chat_message("ariadne", "Approval received. Continuing..." if approved else "Proposal rejected.")

    def on_editor_message(self, message: EditorMessage) -> None:
        self.add_chat_message("ariadne", "Suspending TUI for external editor intervention...")
        with self.suspend():
            try:
                subprocess.run(shlex.split(message.command))
            except Exception as e:
                logging.error(f"Failed to run editor: {e}")
            finally:
                message.completion_event.set()
        self.add_chat_message("ariadne", "Intervention complete. Resuming...")

    def update_intent(self, intent: str) -> None:
        self.query_one("#intent-display", Static).update(intent)

    def update_files(self, files: List[str]) -> None:
        display = self.query_one("#files-display", Static)
        current = display.renderable
        if current == "None":
            display.update("\n".join(files))
        else:
            display.update(str(current) + "\n" + "\n".join(files))

    def update_test_status(self, success: bool, output: str) -> None:
        display = self.query_one("#test-display", Static)
        status = "[bold green]PASSED[/]" if success else "[bold red]FAILED[/]"
        display.update(f"{status}\n\n[dim]{output[:100]}...[/]")

    def action_clear_chat(self) -> None:
        self.query_one("#chat-log", RichLog).clear()

if __name__ == "__main__":
    AriadneApp().run()
