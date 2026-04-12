import asyncio
from typing import Any, Dict, List

from .base import Service
from ..lsp import LSPManager


class LSPService(Service):
    def __init__(self, command: str = "node", args: List[str] = None, cwd: str = None):
        self.command = command
        self.args = args or ["--stdio", "@microsoft/lsp-mcp-server"]
        self.cwd = cwd
        self._manager = LSPManager(command=self.command, args=self.args, cwd=self.cwd)
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._manager.start())
            self._running = True
        except Exception:
            self._running = False

    def stop(self) -> None:
        if not self._running:
            return
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._manager.stop())
            self._running = False
        except Exception:
            self._running = False

    def is_running(self) -> bool:
        return self._running

    def get_diagnostics(self, filepath: str) -> List[Dict[str, Any]]:
        if not self._running:
            return []
        return self._manager.get_diagnostics(filepath)

    def get_hover(self, filepath: str, line: int, character: int) -> str:
        if not self._running:
            return ""
        return self._manager.get_hover(filepath, line, character)

    def did_change(self, filepath: str, content: str) -> None:
        if not self._running:
            return
        self._manager.did_change(filepath, content)
