import logging
import asyncio
from typing import Any, Dict, List, Optional, Tuple
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("ariadne.lsp")

class LSPManager:
    """
    Manages a persistent connection to an LSP-MCP server.
    """
    def __init__(self, command: str, args: List[str], cwd: Optional[str] = None):
        self.command = command
        self.args = args
        self.cwd = cwd
        self.session: Optional[ClientSession] = None
        self._client_context = None
        self._loop = None
        self._lock = asyncio.Lock()

    async def start(self):
        """Starts the MCP server and initializes the session."""
        if self.session:
            return

        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=None
        )

        # Handle working directory if provided
        old_cwd = None
        if self.cwd:
            old_cwd = os.getcwd()
            os.chdir(self.cwd)
            logger.info(f"Switching to {self.cwd} to start LSP server...")

        try:
            # We need to keep the context manager alive
            self._client_context = stdio_client(server_params)
            read, write = await self._client_context.__aenter__()
            self.session = ClientSession(read, write)
            await self.session.__aenter__()
            await self.session.initialize()
            logger.info(f"LSP-MCP server started: {self.command} {' '.join(self.args)}")
        finally:
            if old_cwd:
                os.chdir(old_cwd)

    async def stop(self):
        """Stops the MCP server."""
        if self.session:
            await self.session.__aexit__(None, None, None)
            await self._client_context.__aexit__(None, None, None)
            self.session = None
            self._client_context = None
            logger.info("LSP-MCP server stopped.")

    async def call_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        """Calls a tool on the MCP server."""
        if not self.session:
            await self.start()
        
        async with self._lock:
            try:
                result = await self.session.call_tool(tool_name, tool_args)
                return result
            except Exception as e:
                logger.error(f"LSP-MCP tool call failed ({tool_name}): {e}")
                return None

    def call_tool_sync(self, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        """Synchronous wrapper for call_tool."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(self.call_tool(tool_name, tool_args))

    def get_diagnostics(self, filepath: str) -> List[Dict[str, Any]]:
        """Queries for diagnostics on a specific file."""
        result = self.call_tool_sync("workspace/diagnostics", {"uri": f"file://{filepath}"})
        if not result:
            return []
        
        # Depending on lsp-mcp implementation, result might be a list or a dict
        # Assuming result.content[0].text contains JSON string if it's a TextContent
        if hasattr(result, "content") and result.content:
            try:
                import json
                data = json.loads(result.content[0].text)
                return data.get("items", [])
            except Exception:
                return []
        return []

    def get_hover(self, filepath: str, line: int, character: int) -> str:
        """Queries for hover info at a specific position."""
        result = self.call_tool_sync("textDocument/hover", {
            "uri": f"file://{filepath}",
            "position": {"line": line, "character": character}
        })
        if hasattr(result, "content") and result.content:
            return result.content[0].text
        return ""

    def did_change(self, filepath: str, content: str):
        """Notifies the LSP server of a file change (shadow buffer)."""
        self.call_tool_sync("textDocument/didChange", {
            "uri": f"file://{filepath}",
            "text": content
        })
