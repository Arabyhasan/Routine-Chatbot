"""
mcp_client.py — MCP client for the routine agent (mcp v2 SDK).

Unlike chatbot.py (which calls mcp_tools.execute() directly in-process),
this client speaks the actual MCP protocol: it spawns mcp_server.py as a
stdio subprocess, fetches the live tool list from it, and routes every
tool call through the MCP session. Tool schemas are never hardcoded here —
they come from the server, so mcp_server.py stays the single source of
truth for what tools exist.

Model calls go through llm_provider.LLMProvider, so this client gets the
same Claude / Groq / Gemini fallback behaviour as chatbot.py and web_app.py.

Usage:
  python mcp_client.py                  # spawns ./mcp_server.py
  python mcp_client.py path/to/server.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_types import TextContent

from llm_provider import LLMProvider
from routine_manager import load_routine

MAX_TOOL_ROUNDS = 6  # matches chatbot.py's agent loop cap


def _server_params(server_script_path: str) -> StdioServerParameters:
    """Describe the subprocess that runs the MCP server."""
    if not server_script_path.endswith(".py"):
        raise ValueError("Server script must be a .py file")
    return StdioServerParameters(command=sys.executable, args=[server_script_path])


class MCPClient:
    """Holds the MCP session, the LLM provider, and conversation history."""

    def __init__(self):
        self.provider = LLMProvider()
        self.history: list[dict] = []
        self.tools: list[dict] = []  # Anthropic-schema tool list, fetched from server

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
            "- For emails: show the draft first and confirm before sending, unless told to send directly.\n"
        )

    # ─── Server connection ────────────────────────────────────────────────

    async def connect(self, client: Client) -> None:
        tool_list = await client.list_tools()
        self.tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tool_list.tools
        ]
        print("\nConnected to server with tools:", [t["name"] for t in self.tools])

    # ─── Agent loop (mirrors chatbot.py's RoutineAgent.respond) ───────────

    async def process_query(self, client: Client, query: str) -> str:
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
                    print(f"[Calling tool {tc['name']} with args {tc['input']}]")
                    call_result = await client.call_tool(tc["name"], tc["input"] or {})
                    text = "\n".join(
                        block.text for block in call_result.content
                        if isinstance(block, TextContent)
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": text,
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

    async def chat_loop(self, client: Client) -> None:
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
                response = await self.process_query(client, query)
                print("\n" + response)
            except Exception as e:
                print(f"\nError: {e}")


async def main() -> None:
    default_server = str(Path(__file__).resolve().parent / "mcp_server.py")
    server_script_path = sys.argv[1] if len(sys.argv) > 1 else default_server

    mcp_client = MCPClient()

    async with Client(stdio_client(_server_params(server_script_path))) as client:
        await mcp_client.connect(client)
        await mcp_client.chat_loop(client)


if __name__ == "__main__":
    asyncio.run(main())
