"""
mcp_agent_session.py — runs a real MultiServerMCP-backed agent session
(local mcp_server.py + Slack's official MCP server, when enabled) behind a
synchronous interface that web_app.py's http.server-based handler can call
directly, without either side needing to become fully async.

Why this exists: mcp_client.py's MCPClient + MultiServerMCP are async, built
for a terminal loop that owns the whole process. web_app.py is a synchronous
http.server handling one request at a time. Reconnecting a fresh MCP session
on every single chat message would be slow (spawns a subprocess per message)
and would lose conversation state. Instead, AgentSession opens ONE connection
per login session, on a dedicated background thread running its own asyncio
event loop, and exposes plain synchronous methods that submit work to that
loop and block for the result — the standard pattern for bridging sync and
async code that must coexist.

Usage:
    session = AgentSession(
        routine_path="profiles/araby/routine.json",
        google_token_path="profiles/araby/token.json",
        knowledge_path="profiles/araby/knowledge_store.json",
        slack_token_path="profiles/araby/slack_token.json" or None,
    )
    session.start()
    reply = session.chat("what's my schedule today?")
    tools = session.tool_names()
    session.stop()
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from mcp_client import MCPClient
from multi_server_mcp import MultiServerMCP, RemoteServer, StdioServer

SLACK_MCP_URL = "https://mcp.slack.com/mcp"


class AgentSession:
    def __init__(
        self,
        routine_path: str,
        google_token_path: Optional[str] = None,
        google_credentials_path: str = "credentials.json",
        knowledge_path: Optional[str] = None,
        slack_token_path: Optional[str] = None,
        service_env: Optional[dict] = None,
    ):
        self.routine_path = routine_path
        self.google_token_path = google_token_path
        self.google_credentials_path = google_credentials_path
        self.knowledge_path = knowledge_path
        self.slack_token_path = slack_token_path
        self.service_env = service_env or {}

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._multi: Optional[MultiServerMCP] = None
        self.client = MCPClient()
        self.tools: list[dict] = []
        self.last_error: Optional[str] = None

    # ─── Background loop plumbing ───────────────────────────────────────

    def _run_loop(self, ready: threading.Event) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        ready.set()
        self._loop.run_forever()

    def _submit(self, coro, timeout: float = 60.0):
        if not self._loop or not self._loop.is_running():
            raise RuntimeError("Agent session is not running.")
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    # ─── Lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait()
        self._submit(self._connect())

    async def _connect(self) -> None:
        env = {"ROUTINE_AGENT_ROUTINE_PATH": self.routine_path}
        if self.google_token_path:
            env["GOOGLE_CALENDAR_TOKEN_PATH"] = self.google_token_path
        if self.google_credentials_path:
            env["GOOGLE_CALENDAR_CREDENTIALS_PATH"] = self.google_credentials_path
        if self.knowledge_path:
            env["ROUTINE_AGENT_KNOWLEDGE_PATH"] = self.knowledge_path
        # Inherit the parent's environment (LLM API keys, ServiceConfig flags,
        # etc.) and layer our per-profile path overrides + mode selection on top.
        full_env = {**os.environ, **env, **self.service_env}

        server_script = str(Path(__file__).resolve().parent / "mcp_server.py")
        servers = [StdioServer(command=sys.executable, args=[server_script], label="routine", env=full_env)]

        if self.slack_token_path and os.getenv("ENABLE_SLACK_MCP", "").lower() in ("1", "true", "yes"):
            try:
                from slack_mcp_auth import build_slack_http_client
                http_client = await build_slack_http_client(token_path=Path(self.slack_token_path))
                if http_client:
                    servers.append(RemoteServer(url=SLACK_MCP_URL, http_client=http_client, label="slack"))
            except Exception as exc:
                self.last_error = f"Slack MCP connection failed: {exc}"

        self._multi = MultiServerMCP(servers)
        await self._multi.__aenter__()
        self.tools = await self._multi.list_tools()
        self.client.tools = self.tools

    def stop(self) -> None:
        if self._loop and self._loop.is_running():
            try:
                self._submit(self._disconnect(), timeout=10)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)

    async def _disconnect(self) -> None:
        if self._multi:
            await self._multi.__aexit__(None, None, None)

    # ─── Public sync API used by web_app.py ────────────────────────────

    def chat(self, message: str) -> str:
        return self._submit(self.client.process_query(self._multi, message), timeout=120)

    def clear_history(self) -> None:
        self.client.history = []

    def tool_names(self) -> list[str]:
        return [t["name"] for t in self.tools]

    def call_tool(self, name: str, args: dict):
        return self._submit(self._multi.call_tool(name, args), timeout=60)

    def sync_sheets(self) -> str:
        result = self.call_tool("sync_to_sheets", {})
        return result.text
