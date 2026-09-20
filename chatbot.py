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

from dotenv import load_dotenv
load_dotenv()

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
            from knowledge_base import KnowledgeBase
            self.knowledge_base = KnowledgeBase(knowledge_base_path)
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

        return (
            f"You are a personal scheduling and productivity assistant. Today is {today}.\n\n"
            f"Current routine:\n{schedule_str}\n\n"
            f"Connected services: Slack ({slack_status}), Gmail ({gmail_status}), Sheets ({sheets_status}).\n"
            f"{sheets_line}\n\n"
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

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return "ANTHROPIC_API_KEY is not set. Add it to your .env file:\n  ANTHROPIC_API_KEY=sk-ant-..."

        try:
            import anthropic as _anthropic
        except ImportError:
            return "anthropic package not installed. Run: pip install anthropic"

        text = user_input.strip()

        # ── Pending email shortcut ─────────────────────────────────────────
        # Intercept confirm/cancel before hitting the LLM to be snappy
        import re
        lowered = text.lower()
        if self.tool_ctx.pending_email:
            if re.search(r"\b(send it|confirm|yes[,.]? send|approve)\b", lowered):
                return execute_tool(self.tool_ctx, "confirm_pending_email", {"confirm": "yes"})
            if re.search(r"\b(cancel|reject|don't send|do not send|no)\b", lowered):
                return execute_tool(self.tool_ctx, "confirm_pending_email", {"confirm": "no"})

        client = _anthropic.Anthropic(api_key=api_key)
        self.history.append({"role": "user", "content": text})
        messages = self.history[-self.MAX_HISTORY:]

        # Primary model with automatic fallback on model-not-found errors
        model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        fallback = os.getenv("CLAUDE_FALLBACK_MODEL", "claude-3-5-haiku-latest")

        for _ in range(6):  # max tool rounds
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=1024,
                    system=self._build_system_prompt(),
                    tools=ANTHROPIC_TOOLS,
                    messages=messages,
                )
            except Exception as exc:
                # Auto-retry with fallback if the model string is wrong
                if model != fallback and "model" in str(exc).lower():
                    model = fallback
                    continue
                return f"Claude API error: {exc}"

            stop = getattr(response, "stop_reason", None)

            if stop == "end_turn":
                text_out = next(
                    (b.text for b in response.content if getattr(b, "type", "") == "text"),
                    "I couldn't generate a response. Please try again.",
                )
                self.history.append({"role": "assistant", "content": self._content_to_dicts(response.content)})
                return text_out

            if stop == "tool_use":
                assistant_dicts = self._content_to_dicts(response.content)
                messages.append({"role": "assistant", "content": assistant_dicts})
                self.history.append({"role": "assistant", "content": assistant_dicts})

                tool_results = []
                for block in response.content:
                    if getattr(block, "type", "") == "tool_use":
                        # All tool logic lives in mcp_tools.execute()
                        result = execute_tool(self.tool_ctx, block.name, dict(block.input or {}))
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                messages.append({"role": "user", "content": tool_results})
                self.history.append({"role": "user", "content": tool_results})
                continue

            break  # unexpected stop_reason

        return "I ran into an issue processing that. Please try again."

    def clear_history(self):
        self.history = []
        self.tool_ctx.pending_email = None

    def startup_check(self) -> str:
        lines = []
        if os.getenv("ANTHROPIC_API_KEY"):
            lines.append("Claude API: configured")
        else:
            lines.append("Claude API: ANTHROPIC_API_KEY not set (required)")
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
