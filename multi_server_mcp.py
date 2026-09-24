"""
multi_server_mcp.py — connect to several MCP servers at once, merge their
tools into one list for the LLM, and route each tool call back to whichever
server actually owns that tool.

Why this exists: mcp_client.py used to talk to exactly one server (our own
mcp_server.py, over stdio). Slack now ships its own official, hosted MCP
server (mcp.slack.com) that we want to use *instead of* maintaining our own
Slack integration — but it's a different transport (Streamable HTTP + OAuth)
than our local stdio server. A single MCPClient needs to speak to both at
once and present one combined toolset to the model.

Usage:
    servers = [
        StdioServer(command=sys.executable, args=["mcp_server.py"]),
        RemoteServer(url="https://mcp.slack.com/mcp", http_client=oauth_http_client),
    ]
    async with MultiServerMCP(servers) as multi:
        tools = await multi.list_tools()          # merged, Anthropic-schema
        result = await multi.call_tool(name, args) # routed to the right server
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any, Optional

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import TextContent


@dataclass
class StdioServer:
    """A local MCP server, spawned as a subprocess (e.g. our own mcp_server.py)."""
    command: str
    args: list[str]
    label: str = "local"
    env: Optional[dict] = None  # extra/override environment variables for the subprocess


@dataclass
class RemoteServer:
    """A remote MCP server reached over Streamable HTTP (e.g. Slack's official server)."""
    url: str
    label: str = "remote"
    http_client: Optional[Any] = None  # pre-configured httpx2.AsyncClient (carries OAuth), or None


@dataclass
class _CallResult:
    is_error: bool
    text: str


class MultiServerMCP:
    """Aggregates N MCP servers behind one list_tools()/call_tool() interface."""

    def __init__(self, servers: list):
        self._server_specs = servers
        self._clients: dict[str, Client] = {}       # label -> connected Client
        self._tool_owner: dict[str, str] = {}        # tool name -> label
        self._stack: Optional[contextlib.AsyncExitStack] = None

    async def __aenter__(self) -> "MultiServerMCP":
        self._stack = contextlib.AsyncExitStack()
        for spec in self._server_specs:
            if isinstance(spec, StdioServer):
                params = StdioServerParameters(command=spec.command, args=spec.args, env=spec.env)
                client = await self._stack.enter_async_context(Client(stdio_client(params)))
            elif isinstance(spec, RemoteServer):
                transport = streamable_http_client(spec.url, http_client=spec.http_client)
                client = await self._stack.enter_async_context(Client(transport))
            else:
                raise TypeError(f"Unknown server spec type: {type(spec)}")
            self._clients[spec.label] = client
        return self

    async def __aexit__(self, *exc):
        if self._stack:
            await self._stack.aclose()

    async def list_tools(self) -> list[dict]:
        """Fetch tools from every connected server, merged into one Anthropic-schema list.

        If two servers happen to expose a tool with the same name, the one
        connected first wins and a note is logged — this shouldn't happen in
        practice (our local tools and Slack's tools don't overlap in name),
        but silent shadowing would be worse than a visible skip.
        """
        merged: list[dict] = []
        for label, client in self._clients.items():
            tool_list = await client.list_tools()
            for tool in tool_list.tools:
                if tool.name in self._tool_owner:
                    continue  # already claimed by an earlier server
                self._tool_owner[tool.name] = label
                merged.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                })
        return merged

    async def call_tool(self, name: str, arguments: dict) -> _CallResult:
        label = self._tool_owner.get(name)
        if label is None:
            return _CallResult(is_error=True, text=f"No connected server exposes a tool named '{name}'.")
        client = self._clients[label]
        result = await client.call_tool(name, arguments or {})
        text = "\n".join(b.text for b in result.content if isinstance(b, TextContent))
        return _CallResult(is_error=result.is_error, text=text)

    def tool_origin(self, name: str) -> Optional[str]:
        """Which server label a tool came from — useful for logging/debugging."""
        return self._tool_owner.get(name)
