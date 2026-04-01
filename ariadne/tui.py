import logging
import threading
import sys
import subprocess
import shlex
import pyperclip
from datetime import datetime
from typing import Any, Dict, Optional, List, Callable

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, Grid, VerticalScroll
from textual.widgets import Header, Footer, Static, RichLog, TabbedContent, TabPane, Button, Input, Label
from textual.reactive import reactive
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.binding import Binding
from textual.geometry import Offset

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

class EditorMessage(Message):
    """Sent to request an external editor launch."""
    def __init__(self, command: str, completion_event: threading.Event) -> None:
        self.command = command
        self.completion_event = completion_event
        super().__init__()

class RedirectOutput:
    """Redirects stdout/stderr to the Textual app via messages."""
    def __init__(self, app: App):
        self.app = app

    def write(self, text: str):
        if text.strip():
            self.app.post_message(StdoutMessage(text))

    def flush(self):
        pass

class PromptUserMessage(Message):
    """Sent to request user approval for a proposal."""
    def __init__(self, proposal: str, response_event: threading.Event, response_container: Dict[str, bool]) -> None:
        self.proposal = proposal
        self.response_event = response_event
        self.response_container = response_container
        super().__init__()

class SetupScreen(ModalScreen[Optional[Dict[str, Any]]]):
    """
    Keyboard-centric setup screen.
    """
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "submit", "Start Engine", priority=True),
    ]

    def __init__(self, initial_intent: str = "", initial_targets: str = "") -> None:
        super().__init__()
        self.initial_intent = initial_intent
        self.initial_targets = initial_targets

    def compose(self) -> ComposeResult:
        with Vertical(id="setup-container"):
            yield Label("[bold blue]ARIADNE ENGINE SETUP[/]", id="setup-title")
            yield Label("[bold white]Intent[/]")
            yield Input(value=self.initial_intent, placeholder="Objective...", id="intent-input")
            yield Label("\n[bold white]Targets[/]")
            yield Input(value=self.initial_targets, placeholder="Files/Dirs...", id="targets-input")
            yield Label("\n[dim]TAB: Navigate | ENTER: Start | ESC: Cancel[/]", id="setup-hint")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        intent = self.query_one("#intent-input", Input).value
        targets = self.query_one("#targets-input", Input).value
        self.dismiss({"intent": intent, "targets": targets})

    def on_mount(self) -> None:
        self.query_one("#intent-input", Input).focus()

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
            f"[bold blue]ENGINE STATUS[/]\n"
            f"────────────────\n"
            f"State:   [bold green]{self.state_name}[/]\n"
            f"Retries: [bold yellow]{self.retry_count}[/]\n"
            f"Elapsed: {str(elapsed).split('.')[0]}\n"
        )

class AriadneApp(App):
    """
    The main keyboard-driven Ariadne Dashboard.
    """
    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("h", "prev_tab", "Prev Tab"),
        Binding("l", "next_tab", "Next Tab"),
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
        Binding("y", "yank", "Yank"),
        Binding("c", "open_setup", "Configure"),
        Binding("enter", "approve", "Approve", show=False),
        Binding("escape", "reject", "Reject", show=False),
        Binding("f1", "switch_tab('help-tab')", "Help"),
    ]

    engine_running = reactive(False)
    prompt_active = reactive(False)
    scrolled_to_bottom = reactive(False)

    CSS = """
    Screen { background: #1a1b26; }
    #sidebar {
        width: 30;
        background: #24283b;
        border-right: solid #414868;
        padding: 1;
    }
    #main-content { width: 1fr; }
    RichLog { background: #1a1b26; color: #a9b1d6; }
    .log-info { color: #7aa2f7; }
    .log-warning { color: #e0af68; }
    .log-error { color: #f7768e; }

    ModalScreen { align: center middle; }

    #setup-container {
        width: 60;
        height: auto;
        background: #24283b;
        border: double #7aa2f7;
        padding: 2;
    }
    #setup-title { text-align: center; margin-bottom: 1; }
    #setup-hint { text-align: center; margin-top: 1; }

    #help-content, #plan-display, #surgeon-display, #history-display, #review-text, #test-output {
        padding: 1 2;
        color: #a9b1d6;
    }
    #plan-display, #surgeon-display, #history-display, #review-scroll, #test-scroll {
        overflow-y: scroll;
    }
    #review-scroll, #test-scroll {
        border: solid #414868;
        background: #1a1b26;
    }
    #review-header {
        text-align: center;
        padding: 1;
        background: #f7768e;
        color: white;
    }
    #scroll-warning { text-align: center; padding: 1; color: #e0af68; }
    #scroll-warning.complete { color: #9ece6a; }
    
    .hidden { display: none; }
    .review-active #sidebar { border-right: solid #f7768e; }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.start_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self.initial_setup_data: Dict[str, str] = {"intent": "", "targets": ""}
        self.current_prompt_event: Optional[threading.Event] = None
        self.current_prompt_container: Optional[Dict[str, bool]] = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield EngineStatus(id="engine-status")
                yield Static("\n[bold blue]ACTIVE INTENT[/]\n[italic]Waiting...[/]", id="intent-display")
                yield Static("\n[bold cyan]STATUS[/]\n[white]Idle[/]", id="runtime-status")
            with Container(id="main-content"):
                with TabbedContent(id="tabs"):
                    with TabPane("Logs", id="logs-tab"):
                        yield RichLog(id="engine-logs", highlight=True, markup=True)
                    with TabPane("Plan", id="plan-tab"):
                        yield Static("No active plan.", id="plan-display")
                    with TabPane("Surgeon", id="surgeon-tab"):
                        yield Static("Waiting for MAPS state...", id="surgeon-display")
                    with TabPane("History", id="history-tab"):
                        yield Static("No history yet.", id="history-display")
                    with TabPane("Tests", id="tests-tab"):
                        with VerticalScroll(id="test-scroll"):
                            yield Static("No test output yet.", id="test-output")
                    with TabPane("Review", id="review-tab"):
                        yield Label("[bold]PENDING CONTRACT REVIEW[/]", id="review-header")
                        with VerticalScroll(id="review-scroll"):
                            yield Static("No proposal.", id="review-text")
                        yield Label("[bold yellow]SCROLL TO BOTTOM TO APPROVE[/]", id="scroll-warning")
        yield Footer()

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "open_setup":
            return not self.engine_running and not self.prompt_active
        if action in ("approve", "reject"):
            return self.prompt_active
        if action == "approve":
            return self.prompt_active and self.scrolled_to_bottom
        return True

    def watch_prompt_active(self, active: bool) -> None:
        if active:
            self.add_class("review-active")
            self.query_one(TabbedContent).active = "review-tab"
            self.query_one("#runtime-status", Static).update("[bold red]Action Required[/]")
            self.bind("enter", "approve", description="Approve", show=True)
            self.bind("escape", "reject", description="Reject", show=True)
            scroll_view = self.query_one("#review-scroll", VerticalScroll)
            self.watch(scroll_view, "scroll_offset", self.check_review_scroll)
            self.check_review_scroll()
        else:
            self.remove_class("review-active")
            self.query_one("#runtime-status", Static).update("[bold white]Running[/]" if self.engine_running else "[bold white]Idle[/]")
            self.bind("enter", "approve", show=False)
            self.bind("escape", "reject", show=False)

    def check_review_scroll(self) -> None:
        if not self.prompt_active: return
        scroll_view = self.query_one("#review-scroll", VerticalScroll)
        if scroll_view.scroll_offset.y + scroll_view.content_size.height >= scroll_view.virtual_size.height - 1:
            self.scrolled_to_bottom = True

    def watch_scrolled_to_bottom(self, value: bool) -> None:
        if self.prompt_active:
            warning = self.query_one("#scroll-warning", Label)
            if value:
                warning.update("[bold green]Review Complete. Press ENTER to Approve.[/]")
                warning.add_class("complete")
            else:
                warning.update("[bold yellow]SCROLL TO BOTTOM TO APPROVE[/]")
                warning.remove_class("complete")

    def action_approve(self) -> None:
        if self.scrolled_to_bottom:
            self.resolve_prompt(True)

    def action_reject(self) -> None:
        self.resolve_prompt(False)

    def resolve_prompt(self, approved: bool) -> None:
        if self.current_prompt_container and self.current_prompt_event:
            self.current_prompt_container["approved"] = approved
            self.current_prompt_event.set()
            self.prompt_active = False
            self.query_one(TabbedContent).active = "logs-tab"

    def action_open_setup(self) -> None:
        if self.engine_running or self.prompt_active: return
        def handle_setup(setup_data: Optional[Dict[str, Any]]) -> None:
            if setup_data and self.start_callback:
                self.engine_running = True
                self.update_intent(setup_data["intent"])
                self.start_callback(setup_data)
        self.push_screen(SetupScreen(
            initial_intent=self.initial_setup_data.get("intent", ""),
            initial_targets=self.initial_setup_data.get("targets", "")
        ), handle_setup)

    def action_next_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        all_tabs = [p.id for p in tabs.query(TabPane)]
        idx = all_tabs.index(tabs.active)
        tabs.active = all_tabs[(idx + 1) % len(all_tabs)]

    def action_prev_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        all_tabs = [p.id for p in tabs.query(TabPane)]
        idx = all_tabs.index(tabs.active)
        tabs.active = all_tabs[(idx - 1) % len(all_tabs)]

    def action_scroll_down(self) -> None:
        self._scroll(1)

    def action_scroll_up(self) -> None:
        self._scroll(-1)

    def _scroll(self, direction: int) -> None:
        tabs = self.query_one(TabbedContent)
        active = tabs.active
        if active == "logs-tab":
            log = self.query_one("#engine-logs", RichLog)
            log.scroll_down() if direction > 0 else log.scroll_up()
        elif active == "tests-tab":
            scroll = self.query_one("#test-scroll", VerticalScroll)
            scroll.scroll_down() if direction > 0 else scroll.scroll_up()
        elif active == "review-tab":
            scroll = self.query_one("#review-scroll", VerticalScroll)
            scroll.scroll_down() if direction > 0 else scroll.scroll_up()
            self.check_review_scroll()
        else:
            try:
                pane = tabs.query_one(f"#{active}")
                widget = pane.query_one(Static)
                widget.scroll_down() if direction > 0 else widget.scroll_up()
            except Exception: pass

    def action_yank(self) -> None:
        """Copies content of the active tab to clipboard."""
        tabs = self.query_one(TabbedContent)
        active = tabs.active
        text = ""
        label = ""

        if active == "tests-tab":
            text = str(self.query_one("#test-output", Static).renderable)
            label = "Test Output"
        elif active == "review-tab":
            text = str(self.query_one("#review-text", Static).renderable)
            label = "Proposed Contract"
        elif active == "plan-tab":
            text = str(self.query_one("#plan-display", Static).renderable)
            label = "Active Plan"

        if text:
            pyperclip.copy(text)
            self.notify(f"Copied {label} to clipboard!", severity="information")
        else:
            self.notify("Nothing to copy in this tab.", severity="warning")

    def on_mount(self) -> None:
        self.title = "Ariadne ECU Dashboard"
        handler = TextualLogHandler(self)
        logging.getLogger("ariadne").addHandler(handler)
        redirector = RedirectOutput(self)
        sys.stdout = sys.stderr = redirector
        if self.start_callback: self.action_open_setup()
        
    def on_engine_log_message(self, message: EngineLogMessage) -> None:
        try:
            log = self.query_one("#engine-logs", RichLog)
            ts = datetime.fromtimestamp(message.record.created).strftime("%H:%M:%S")
            log.write(f"[{ts}] [{message.record.levelname}] {message.record.getMessage()}")
        except Exception: pass

    def on_stdout_message(self, message: StdoutMessage) -> None:
        try:
            log = self.query_one("#engine-logs", RichLog)
            log.write(f"[dim white]{message.text.strip()}[/]")
        except Exception: pass

    def on_state_transition_message(self, message: StateTransitionMessage) -> None:
        try:
            status = self.query_one("#engine-status", EngineStatus)
            status.state_name, status.retry_count = message.state_name, message.retry_count
            if message.state_name == "FINISH": self.engine_running = False
        except Exception: pass

    def on_prompt_user_message(self, message: PromptUserMessage) -> None:
        self.current_prompt_event, self.current_prompt_container = message.response_event, message.response_container
        self.query_one("#review-text", Static).update(message.proposal)
        self.scrolled_to_bottom = False
        self.prompt_active = True

    def on_editor_message(self, message: EditorMessage) -> None:
        """Handles external editor requests by suspending the TUI."""
        with self.suspend():
            try:
                subprocess.run(shlex.split(message.command))
            except Exception as e:
                logging.error(f"Failed to run editor: {e}")
            finally:
                message.completion_event.set()
        
    def update_intent(self, intent: str) -> None:
        try: self.query_one("#intent-display", Static).update(f"\n[bold blue]ACTIVE INTENT[/]\n{intent}")
        except Exception: pass

    def update_plan(self, data: Dict[str, Any]) -> None:
        try:
            text = f"[bold green]ARCHITECT REASONING[/]\n{data.get('reasoning', '')}\n\n[bold green]SENSING STEPS[/]\n"
            for i, s in enumerate(data.get("steps", [])):
                text += f"{i+1}. [bold cyan]{s.get('symbol', 'unknown')}[/]\n"
            self.query_one("#plan-display", Static).update(text)
        except Exception: pass

    def update_surgeon(self, symbol: str, code: str, edits: List[Dict[str, Any]] = None) -> None:
        try:
            text = f"[bold red]SURGEON: OPERATING ON {symbol}[/]\n\n[bold blue]Target Code:[/]\n```\n{code}\n```\n"
            if edits:
                text += "\n[bold green]Queued Edits:[/]\n"
                for i, e in enumerate(edits):
                    text += f"{i+1}. [italic]{e.get('search_text', '')[:30]}...[/] -> [italic]{edit.get('replace_text', '')[:30]}...[/]\n"
            self.query_one("#surgeon-display", Static).update(text)
        except Exception: pass

    def update_history(self, history: List[str]) -> None:
        try:
            text = "[bold yellow]REPAIR HISTORY[/]\n"
            for i, entry in enumerate(history): text += f"{i+1}. {entry}\n"
            self.query_one("#history-display", Static).update(text)
        except Exception: pass

    def write_test_output(self, output: str) -> None:
        try: self.query_one("#test-output", Static).update(output)
        except Exception: pass

if __name__ == "__main__":
    AriadneApp().run()
