"""
mcp_client.py — MCP client for the routine agent (mcp v2 SDK).

Unlike chatbot.py (which calls mcp_tools.execute() directly in-process),
this client speaks the actual MCP protocol, and can talk to MULTIPLE MCP
servers at once via multi_server_mcp.MultiServerMCP:

  - our own mcp_server.py (local, stdio) — routine/scheduling/weather/email
  - Slack's official, hosted MCP server (remote, OAuth) — messaging/search,
    used INSTEAD of maintaining our own Slack bot-token integration

Set ENABLE_SLACK_MCP=true in .env to turn on the Slack connection. The
first time you do, a browser window opens for Slack login — same one-time
approval flow as Google's OAuth, except a Slack workspace admin also has
to approve the MCP integration once, on Slack's side, before this can
connect (that step can't be done from code).

Tool schemas are never hardcoded here — they come from whichever server(s)
are connected, so mcp_server.py (and Slack's own server) stay the single
source of truth for what tools exist.

Usage:
  python mcp_client.py                  # spawns ./mcp_server.py (+ Slack if enabled)
  python mcp_client.py path/to/server.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from pathlib import Path

from env_loader import load_project_env
load_project_env()

from llm_provider import LLMProvider
from multi_server_mcp import MultiServerMCP, RemoteServer, StdioServer
from routine_manager import load_routine

MAX_TOOL_ROUNDS = 6  # matches chatbot.py's agent loop cap
SLACK_MCP_URL = "https://mcp.slack.com/mcp"


async def _build_server_list(server_script_path: str) -> list:
    servers = [StdioServer(command=sys.executable, args=[server_script_path], label="routine")]

    if os.getenv("ENABLE_SLACK_MCP", "").lower() in ("1", "true", "yes"):
        try:
            from slack_mcp_auth import build_slack_http_client
            http_client = await build_slack_http_client()
            if http_client:
                servers.append(RemoteServer(url=SLACK_MCP_URL, http_client=http_client, label="slack"))
                print("Slack MCP server connected — Slack's own tools are now available.")
            else:
                print("Slack MCP setup did not complete — continuing without it.")
        except Exception as exc:
            print(f"Could not connect Slack's MCP server ({exc}) — continuing without it.")

    return servers


class MCPClient:
    """Holds the multi-server MCP connection, the LLM provider, and conversation history."""

    def __init__(self):
        self.provider = LLMProvider()
        self.history: list[dict] = []
        self.tools: list[dict] = []  # Anthropic-schema tool list, merged from every connected server

    # ─── System prompt ────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        today = date.today().strftime("%A, %B %d, %Y")
        try:
            commitments = load_routine("routine.json")
            lines = []
            for c in commitments[:12]:
                days = ", ".join(d.value for d in c.days)
                lock = " [fixed]" if not c.reschedulable else ""
                lines.append(f"  - {c.title}: {days}, {c.time_slot.pretty()}{lock} (priority {c.priority})")
            schedule_str = "\n".join(lines) or "  (no commitments yet)"
        except Exception:
            schedule_str = "  (schedule unavailable — use the read_schedule tool)"

        return (
            f"You are a personal scheduling and productivity assistant. Today is {today}.\n\n"
            f"Current routine:\n{schedule_str}\n\n"
            f"Running on: {self.provider.display_name}\n\n"
            "Guidelines:\n"
            "- Be conversational and concise. Never mention tool names or internal steps.\n"
            "- Always use tools for real data — never guess from memory.\n"
            "- Call check_time_slot or read_schedule before scheduling anything.\n"
            "- If a conflict exists, explain it and offer alternatives via get_free_slots.\n"
            "- For weather questions, always use the get_weather tool — never guess.\n"
            "- For emails: show the draft first and confirm before sending, unless told to send directly.\n"
            "- For Slack, use whichever Slack tool is available to you — search or post as needed.\n"
        )

    # ─── Server connection ────────────────────────────────────────────────

    async def connect(self, multi: MultiServerMCP) -> None:
        self.tools = await multi.list_tools()
        print("\nConnected — tools available:", [t["name"] for t in self.tools])

    # ─── Agent loop (mirrors chatbot.py's RoutineAgent.respond) ───────────

    async def process_query(self, multi: MultiServerMCP, query: str) -> str:
        if not self.provider.is_configured:
            return self.provider.not_configured_message()

        self.history.append({"role": "user", "content": query})
        messages = self.history[-24:]

        for _ in range(MAX_TOOL_ROUNDS):
            result = self.provider.create_message(
                messages=messages,
                anthropic_tools=self.tools,
                system=self._build_system_prompt(),
            )

            if result["stop_reason"] == "tool_use":
                tool_calls = result["tool_calls"]

                assistant_content: list = []
                if result.get("text"):
                    assistant_content.append({"type": "text", "text": result["text"]})
                for tc in tool_calls:
                    assistant_content.append({
                        "type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"],
                    })
                messages.append({"role": "assistant", "content": assistant_content})
                self.history.append({"role": "assistant", "content": assistant_content})

                tool_results = []
                for tc in tool_calls:
                    origin = multi.tool_origin(tc["name"]) or "?"
                    print(f"[Calling tool {tc['name']} (via {origin}) with args {tc['input']}]")
                    call_result = await multi.call_tool(tc["name"], tc["input"] or {})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": call_result.text,
                        "is_error": call_result.is_error,
                    })

                messages.append({"role": "user", "content": tool_results})
                self.history.append({"role": "user", "content": tool_results})
                continue

            # end_turn (or anything else) — done
            text_out = result["text"] or "I couldn't generate a response. Please try again."
            self.history.append({"role": "assistant", "content": [{"type": "text", "text": text_out}]})
            return text_out

        return "I ran into an issue processing that (too many tool rounds). Please try again."

    # ─── Interactive loop ──────────────────────────────────────────────────

    async def chat_loop(self, multi: MultiServerMCP) -> None:
        print("\nRoutine Agent MCP Client started!")
        print("Type your queries or 'quit' to exit.")

        while True:
            try:
                query = (await asyncio.to_thread(input, "\nQuery: ")).strip()
            except EOFError:
                break

            if query.lower() == "quit":
                break
            if not query:
                continue

            try:
                response = await self.process_query(multi, query)
                print("\n" + response)
            except Exception as e:
                print(f"\nError: {e}")


async def main() -> None:
    default_server = str(Path(__file__).resolve().parent / "mcp_server.py")
    server_script_path = sys.argv[1] if len(sys.argv) > 1 else default_server

    mcp_client = MCPClient()
    servers = await _build_server_list(server_script_path)

    async with MultiServerMCP(servers) as multi:
        await mcp_client.connect(multi)
        await mcp_client.chat_loop(multi)


if __name__ == "__main__":
    asyncio.run(main())
