"""
chatbot.py — Routine Agent powered by Claude tool-use.

Architecture:
  User → Claude (decides which tools to call) → mcp_tools.py (executes) → Claude → User

All tool logic lives in mcp_tools.py — single source of truth used by both
this agent loop and the MCP server (mcp_server.py).
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from env_loader import load_project_env
load_project_env()

from config_loader import Config
from google_integration import GoogleIntegration
from mcp_tools import ToolContext, execute as execute_tool
from routine_manager import load_routine
from service_config import ServiceConfig
from slack_integration import SlackIntegration


# ─── Tool schema definitions (what Claude sees) ───────────────────────────────
# mcp_tools.py has the implementations; this list tells Claude what tools exist.

ANTHROPIC_TOOLS = [
    {
        "name": "read_schedule",
        "description": (
            "Read the user's schedule for a specific day. "
            "Call first when asked about their day, routine, or schedule."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "today, tomorrow, monday, tuesday, etc."}
            },
            "required": ["day"],
        },
    },
    {
        "name": "check_time_slot",
        "description": "Check if the user is free at a specific time. Always call before scheduling.",
        "input_schema": {
            "type": "object",
            "properties": {
                "time": {"type": "string", "description": "Time like '20:00', '8pm', 'evening'"},
                "duration_minutes": {"type": "integer", "default": 60},
                "day": {"type": "string", "default": "today"},
            },
            "required": ["time"],
        },
    },
    {
        "name": "get_free_slots",
        "description": "Get free time slots on a day. Use when asked 'when am I free' or to suggest alternatives.",
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "default": "today"},
                "duration_minutes": {"type": "integer", "default": 60},
            },
        },
    },
    {
        "name": "get_weather",
        "description": "Get live current weather for a city. Use this for weather questions; never invent weather information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City and optional country, e.g. 'Dhaka, Bangladesh'"}
            },
            "required": ["city"],
        },
    },
    {
        "name": "schedule_meeting",
        "description": (
            "Schedule a meeting through the priority engine. "
            "High-priority requesters (e.g. bijoy) can override low-priority commitments (e.g. gym). "
            "Returns: confirm, reschedule_and_confirm, or decline with alternatives."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "time": {"type": "string"},
                "duration_minutes": {"type": "integer", "default": 60},
                "requester_id": {"type": "string", "default": "unknown",
                                 "description": "Slack ID, email, or name like 'bijoy'"},
                "day": {"type": "string", "default": "today"},
            },
            "required": ["title", "time"],
        },
    },
    {
        "name": "reschedule_commitment",
        "description": "Move an existing commitment to a different time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "commitment_title": {"type": "string", "description": "e.g. 'Gym', 'CSE Class'"},
                "new_time": {"type": "string"},
            },
            "required": ["commitment_title", "new_time"],
        },
    },
    {
        "name": "cancel_commitment",
        "description": "Remove a commitment from the routine.",
        "input_schema": {
            "type": "object",
            "properties": {"commitment_title": {"type": "string"}},
            "required": ["commitment_title"],
        },
    },
    {
        "name": "add_recurring_commitment",
        "description": "Add a new recurring commitment (e.g. 'gym every weekday at 8pm').",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "time": {"type": "string"},
                "days": {"type": "array", "items": {"type": "string"},
                         "description": "['monday','tuesday'] or ['weekdays'] or ['everyday']"},
                "commitment_type": {"type": "string", "default": "work_meeting",
                                    "description": "gym, class, deep_work, work_meeting, lunch"},
                "duration_minutes": {"type": "integer", "default": 60},
            },
            "required": ["title", "time", "days"],
        },
    },
    {
        "name": "send_slack_message",
        "description": "Send a message to a Slack channel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name, e.g. 'meeting-times'"},
                "message": {"type": "string"},
            },
            "required": ["channel", "message"],
        },
    },
    {
        "name": "send_email",
        "description": (
            "Draft an email. Default: show the draft and ask for confirmation. "
            "Set send_now=true ONLY if the user explicitly said to send without reviewing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_email": {"type": "string"},
                "subject": {"type": "string"},
                "context": {"type": "string", "description": "What the email should convey."},
                "send_now": {"type": "boolean", "default": False},
            },
            "required": ["to_email", "context"],
        },
    },
    {
        "name": "confirm_pending_email",
        "description": "Send or cancel the pending email draft after user confirms.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confirm": {"type": "string", "description": "yes or no"}
            },
            "required": ["confirm"],
        },
    },
    {
        "name": "remember_fact",
        "description": "Store a user preference or personal fact for future reference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {"type": "string"},
                "category": {"type": "string", "default": "preferences"},
            },
            "required": ["fact"],
        },
    },
    {
        "name": "recall_memory",
        "description": "Recall stored facts and preferences about the user.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_configured_requesters",
        "description": "Show known requesters and their priority levels from config.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "health_check",
        "description": "Check which services (Slack, Gmail, Calendar) are configured.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "sync_to_sheets",
        "description": (
            "Sync the full weekly schedule to Google Sheets and return the sheet URL. "
            "Called automatically after meetings are added, rescheduled, or cancelled. "
            "Also call this when the user asks to 'open the sheet', 'show the spreadsheet', "
            "'update the sheet', or 'what does my sheet look like'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


class RoutineChatbot:
    """
    Routine Agent — Claude as orchestrator with tool-use.

    respond(user_input) → natural language reply

    The agent loop:
      1. Add message to history
      2. Call Claude with ANTHROPIC_TOOLS
      3. Claude returns tool_use → execute via mcp_tools.execute() → feed result back
      4. Claude returns end_turn → return final text
    """

    MAX_HISTORY = 24

    def __init__(
        self,
        config_path: str = "config.yaml",
        routine_path: str = "routine.json",
        service_config: ServiceConfig | None = None,
        knowledge_base_path: str = "knowledge_store.json",  # API compat
    ):
        root = Path(__file__).resolve().parent

        def resolve(p: str) -> str:
            pp = Path(p)
            return str(pp) if (pp.is_absolute() or pp.exists()) else str(root / p)

        self.service_config = service_config or ServiceConfig.from_env()
        self.slack = SlackIntegration() if self.service_config.slack_enabled else None
        self.google = (
            GoogleIntegration()
            if (self.service_config.gmail_enabled or self.service_config.calendar_enabled)
            else None
        )

        # Load knowledge base if available
        try:
            from knowledge_base import UserKnowledgeBase
            self.knowledge_base = UserKnowledgeBase(knowledge_base_path)
        except Exception:
            self.knowledge_base = None

        # ToolContext — passed to every tool call (Cursor's pattern, it's good)
        self.tool_ctx = ToolContext(
            config=Config(resolve(config_path)),
            routine_path=resolve(routine_path),
            slack=self.slack,
            google=self.google,
            knowledge_base=self.knowledge_base,
            service_config=self.service_config,
        )

        self.history: list[dict] = []

        # Optional real MCP client (mcp_client.MCPClient). When set, routine
        # summary / free-slot lookups are delegated to it instead of the
        # in-process tool layer. None by default — chatbot.py works standalone.
        self.mcp_client = None

    # ─── MCP delegation helpers ─────────────────────────────────────────────

    def _mcp_routine_summary(self) -> str:
        """Get a routine summary, via the MCP client if one is attached."""
        if self.mcp_client is not None:
            return self.mcp_client.get_routine_summary()
        return execute_tool(self.tool_ctx, "read_schedule", {"day": "today"})

    def _mcp_free_slots(self):
        """Get today's free slots, via the MCP client if one is attached."""
        if self.mcp_client is not None:
            return self.mcp_client.get_free_slots_for_today()
        return execute_tool(self.tool_ctx, "get_free_slots", {"day": "today"})

    # ─── System prompt ────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        today = date.today().strftime("%A, %B %d, %Y")
        commitments = load_routine(self.tool_ctx.routine_path)
        schedule_lines = []
        for c in commitments[:12]:
            days = ", ".join(d.value for d in c.days)
            lock = " [fixed]" if not c.reschedulable else ""
            schedule_lines.append(f"  - {c.title}: {days}, {c.time_slot.pretty()}{lock} (priority {c.priority})")
        schedule_str = "\n".join(schedule_lines) or "  (no commitments yet)"

        slack_status  = "connected" if (self.slack and getattr(self.slack, "bot_token", None)) else "not configured"
        gmail_status  = "connected" if (self.google and getattr(self.google, "creds", None)) else "not configured"
        sheets_status = "connected" if (self.google and getattr(self.google, "creds", None)) else "not configured"
        sheets_url    = getattr(self.tool_ctx, "sheets_url", None) or ""
        sheets_line   = f"Sheets URL: {sheets_url}" if sheets_url else "Sheets: sync will create the sheet on first mutation."
        from llm_provider import LLMProvider
        provider_line = f"Running on: {LLMProvider().display_name}"

        return (
            f"You are a personal scheduling and productivity assistant. Today is {today}.\n\n"
            f"Current routine:\n{schedule_str}\n\n"
            f"Connected services: Slack ({slack_status}), Gmail ({gmail_status}), Sheets ({sheets_status}).\n"
            f"{sheets_line}\n"
            f"{provider_line}\n\n"
            "Guidelines:\n"
            "- Be conversational and concise. Never mention tool names or internal steps.\n"
            "- Always use tools for real data — never guess from memory.\n"
            "- Call check_time_slot or read_schedule before scheduling anything.\n"
            "- If a conflict exists, explain it and offer alternatives via get_free_slots.\n"
            "- For emails: show the draft first and confirm before sending, unless told to send directly.\n"
            "- Priority system: high-priority requesters (like manager Bijoy) can override "
            "low-priority commitments (like gym). schedule_meeting handles this automatically.\n"
        )

    # ─── SDK → dict conversion ────────────────────────────────────────────────

    def _content_to_dicts(self, content) -> list:
        result = []
        for block in content:
            t = getattr(block, "type", None)
            if t == "text":
                result.append({"type": "text", "text": block.text})
            elif t == "tool_use":
                result.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        return result

    # ─── Agent loop ───────────────────────────────────────────────────────────

    def respond(self, user_input: str) -> str:
        if not (user_input or "").strip():
            return "How can I help with your schedule today?"

        from llm_provider import LLMProvider
        provider = LLMProvider()

        if not provider.is_configured:
            return provider.not_configured_message()

        text    = user_input.strip()
        import re
        lowered = text.lower()

        # ── Pending email shortcut (fast-path, no LLM needed) ─────────────
        if self.tool_ctx.pending_email:
            if re.search(r"\b(send it|confirm|yes[,.]? send|approve)\b", lowered):
                return execute_tool(self.tool_ctx, "confirm_pending_email", {"confirm": "yes"})
            if re.search(r"\b(cancel|reject|don't send|do not send|no)\b", lowered):
                return execute_tool(self.tool_ctx, "confirm_pending_email", {"confirm": "no"})

        self.history.append({"role": "user", "content": text})
        messages = self.history[-self.MAX_HISTORY:]

        for _ in range(6):  # max tool-use rounds
            result = provider.create_message(
                messages=messages,
                anthropic_tools=ANTHROPIC_TOOLS,
                system=self._build_system_prompt(),
            )

            if result["stop_reason"] == "end_turn":
                text_out = result["text"] or "I couldn't generate a response. Please try again."

                # Store in history as Anthropic-format content blocks
                if result.get("_raw"):
                    # Anthropic provider — raw SDK blocks available
                    assistant_dicts = self._content_to_dicts(result["_raw"])
                else:
                    # Groq / Gemini — synthesise Anthropic-format block
                    assistant_dicts = [{"type": "text", "text": text_out}]

                self.history.append({"role": "assistant", "content": assistant_dicts})
                return text_out

            if result["stop_reason"] == "tool_use":
                tool_calls = result["tool_calls"]

                # Build assistant message in Anthropic format (canonical history format)
                assistant_content: list = []
                if result.get("text"):
                    assistant_content.append({"type": "text", "text": result["text"]})
                for tc in tool_calls:
                    assistant_content.append({
                        "type":  "tool_use",
                        "id":    tc["id"],
                        "name":  tc["name"],
                        "input": tc["input"],
                    })

                messages.append({"role": "assistant", "content": assistant_content})
                self.history.append({"role": "assistant", "content": assistant_content})

                # Execute each tool
                tool_results = []
                for tc in tool_calls:
                    res = execute_tool(self.tool_ctx, tc["name"], dict(tc["input"] or {}))
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": tc["id"],
                        "content":     res,
                    })

                messages.append({"role": "user", "content": tool_results})
                self.history.append({"role": "user", "content": tool_results})
                self._last_tool_text = "\n".join(str(r["content"]) for r in tool_results)
                continue

            break

        if getattr(self, "_last_tool_text", None):
            return f"{self._last_tool_text}\n\n(I had trouble wrapping that up neatly — let me know if you need anything else.)"
        return "I ran into an issue processing that. Please try again."

    def clear_history(self):
        self.history = []
        self.tool_ctx.pending_email = None

    def startup_check(self) -> str:
        from llm_provider import LLMProvider
        lines = []
        p = LLMProvider()
        if p.is_configured:
            lines.append(f"LLM provider: {p.display_name}")
        else:
            lines.append("LLM provider: NONE CONFIGURED")
            lines.append("  Free options: GROQ_API_KEY (console.groq.com) or GEMINI_API_KEY (aistudio.google.com)")
        if self.service_config.slack_enabled:
            if self.slack and getattr(self.slack, "bot_token", None):
                lines.append("Slack: configured")
            else:
                lines.append("Slack: SLACK_BOT_TOKEN not set")
        if self.service_config.gmail_enabled or self.service_config.calendar_enabled:
            if self.google and getattr(self.google, "creds", None):
                lines.append("Gmail/Calendar: authenticated")
            else:
                lines.append("Gmail/Calendar: token.json missing")
        routine = load_routine(self.tool_ctx.routine_path)
        lines.append(f"Routine: {len(routine)} commitment(s) loaded")
        return "\n".join(lines)


def main():
    from service_config import prompt_service_selection
    service_config = prompt_service_selection()
    bot = RoutineChatbot(service_config=service_config)
    print(bot.startup_check())
    print("\nRoutine Agent ready. Type 'exit' to quit, 'clear' to reset context.\n")
    while True:
        try:
            prompt = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break
        if prompt.lower() in ("exit", "quit"):
            print("Goodbye.")
            break
        if prompt.lower() == "clear":
            bot.clear_history()
            print("Agent: Conversation context cleared.\n")
            continue
        print(f"Agent: {bot.respond(prompt)}\n")


if __name__ == "__main__":
    main()
