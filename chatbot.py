"""
chatbot.py — Routine Agent powered by Claude tool-use.

Architecture (what was wrong before, what's fixed):
  BEFORE: 170-line if/else chain → Gemini (model probing fails) → same canned reply every time
  AFTER:  User message → Claude with tool definitions → Claude calls tools → Claude responds

Claude is the orchestrator. It reads the user's intent and decides which tools to call.
Tools are the existing business logic (routine_manager, availability, priority, slack, email).
No giant if/else chain. No silent failures. Conversation history is kept for context.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from availability import get_free_slots, is_slot_free
from config_loader import Config
from google_integration import GoogleIntegration
from models import DayOfWeek, MeetingRequest, TimeSlot, Commitment
from priority import handle_meeting_request
from routine_manager import load_routine, save_routine
from service_config import ServiceConfig
from slack_integration import SlackIntegration


# ─── Tool definitions for Claude ─────────────────────────────────────────────
# Claude reads these and decides which to call. Change these to add capabilities.

TOOLS = [
    {
        "name": "read_schedule",
        "description": (
            "Read the user's schedule and commitments for a specific day. "
            "Always call this first when the user asks about their day, routine, or schedule."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {
                    "type": "string",
                    "description": "Which day: 'today', 'tomorrow', 'monday', 'tuesday', etc."
                }
            },
            "required": ["day"]
        }
    },
    {
        "name": "check_time_slot",
        "description": (
            "Check if the user is free at a specific time on a specific day. "
            "Call this before scheduling anything to see if there's a conflict."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "time": {
                    "type": "string",
                    "description": "Time to check, e.g. '20:00', '8pm', '14:30', 'evening'"
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Duration in minutes to check. Default 60.",
                    "default": 60
                },
                "day": {
                    "type": "string",
                    "description": "Which day: 'today', 'tomorrow', 'monday', etc. Default: today.",
                    "default": "today"
                }
            },
            "required": ["time"]
        }
    },
    {
        "name": "get_free_slots",
        "description": (
            "Get a list of free time slots on a given day. "
            "Use when the user asks 'when am I free', or when you need to suggest alternatives."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {
                    "type": "string",
                    "description": "Which day. Default: today.",
                    "default": "today"
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Minimum slot length to look for. Default: 60.",
                    "default": 60
                }
            }
        }
    },
    {
        "name": "schedule_meeting",
        "description": (
            "Schedule a meeting or commitment. Runs through the priority engine — "
            "if the slot is taken, checks whether the requester outranks the conflict "
            "(e.g. manager Bijoy can override gym). "
            "Returns decision: 'confirm', 'reschedule_and_confirm', or 'decline' with alternatives."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Name of the meeting."},
                "time": {"type": "string", "description": "Start time, e.g. '20:00', '8pm'."},
                "duration_minutes": {"type": "integer", "description": "Duration. Default: 60.", "default": 60},
                "requester_id": {
                    "type": "string",
                    "description": "Who is requesting — Slack ID, email, or name like 'bijoy'. Determines override priority. Default: 'unknown'.",
                    "default": "unknown"
                },
                "day": {
                    "type": "string",
                    "description": "Which day. Default: today.",
                    "default": "today"
                }
            },
            "required": ["title", "time"]
        }
    },
    {
        "name": "reschedule_commitment",
        "description": "Move an existing commitment to a new time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "commitment_title": {
                    "type": "string",
                    "description": "Title of the commitment to move, e.g. 'Gym', 'CSE Class'."
                },
                "new_time": {
                    "type": "string",
                    "description": "New start time, e.g. '21:00', '9pm'."
                }
            },
            "required": ["commitment_title", "new_time"]
        }
    },
    {
        "name": "cancel_commitment",
        "description": "Remove a commitment from the routine.",
        "input_schema": {
            "type": "object",
            "properties": {
                "commitment_title": {
                    "type": "string",
                    "description": "Title of the commitment to remove."
                }
            },
            "required": ["commitment_title"]
        }
    },
    {
        "name": "add_recurring_commitment",
        "description": "Add a new recurring commitment to the routine (e.g. 'Add gym every weekday at 8pm').",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Name of the commitment."},
                "time": {"type": "string", "description": "Start time, e.g. '20:00', '8pm'."},
                "days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Days of week: ['monday', 'tuesday', ...] or ['weekdays'] or ['everyday']."
                },
                "commitment_type": {
                    "type": "string",
                    "description": "Type matching config.yaml: gym, class, deep_work, work_meeting, lunch. Default: work_meeting.",
                    "default": "work_meeting"
                },
                "duration_minutes": {"type": "integer", "description": "Duration. Default: 60.", "default": 60}
            },
            "required": ["title", "time", "days"]
        }
    },
    {
        "name": "send_slack_message",
        "description": "Send a message to a Slack channel or DM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "description": "Channel name or ID, e.g. 'meeting-times', '#general'."
                },
                "message": {
                    "type": "string",
                    "description": "Message text to send."
                }
            },
            "required": ["channel", "message"]
        }
    },
    {
        "name": "send_email",
        "description": (
            "Draft and send an email. Uses Claude to write a polished draft. "
            "If Gmail isn't connected, returns the draft for the user to copy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_email": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string", "description": "Email subject line."},
                "context": {
                    "type": "string",
                    "description": "What the email should convey — the assistant will write the actual text."
                }
            },
            "required": ["to_email", "context"]
        }
    }
]


class RoutineChatbot:
    """
    Routine Agent — Claude as orchestrator with tool-use.

    respond(user_input) → natural language reply

    Claude reads the message, decides which tools to call, calls them,
    and formulates the final reply. No if/else routing in Python.
    """

    MAX_HISTORY = 24  # keep last N messages (prevents context overflow on long sessions)

    def __init__(
        self,
        config_path: str = "config.yaml",
        routine_path: str = "routine.json",
        service_config: ServiceConfig | None = None,
        knowledge_base_path: str = "knowledge_store.json",  # kept for API compat
    ):
        project_root = Path(__file__).resolve().parent

        def abs_path(p: str) -> str:
            pp = Path(p)
            return str(pp) if pp.is_absolute() or pp.exists() else str(project_root / p)

        self.config = Config(abs_path(config_path))
        self.routine_path = abs_path(routine_path)
        self.service_config = service_config or ServiceConfig.from_env()

        # External service clients (only init if enabled & configured)
        self.slack = SlackIntegration() if self.service_config.slack_enabled else None
        self.google = (
            GoogleIntegration()
            if (self.service_config.gmail_enabled or self.service_config.calendar_enabled)
            else None
        )

        # Conversation history for multi-turn context
        self.history: list[dict] = []

    # ─── System prompt ────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        today = date.today().strftime("%A, %B %d, %Y")
        commitments = load_routine(self.routine_path)

        schedule_lines = []
        for c in commitments[:12]:
            days = ", ".join(d.value for d in c.days)
            lock = " [fixed]" if not c.reschedulable else ""
            schedule_lines.append(f"  - {c.title}: {days}, {c.time_slot.pretty()}{lock} (priority {c.priority})")
        schedule_str = "\n".join(schedule_lines) if schedule_lines else "  (no commitments yet)"

        slack_status = "connected" if (self.slack and self.slack.bot_token) else "not configured"
        gmail_status = "connected" if (self.google and self.google.creds) else "not configured"

        return (
            f"You are a personal scheduling and productivity assistant. Today is {today}.\n\n"
            f"Current routine:\n{schedule_str}\n\n"
            f"Connected services: Slack ({slack_status}), Gmail ({gmail_status}).\n\n"
            "Guidelines:\n"
            "- Be conversational and concise. Never mention tool names or internal steps.\n"
            "- Use tools to get real data — don't guess from memory.\n"
            "- Always call check_time_slot or read_schedule before scheduling.\n"
            "- If a time conflicts, explain it and offer alternatives via get_free_slots.\n"
            "- For emails: show the draft and confirm before sending, unless told to send directly.\n"
            "- Priority system: high-priority requesters (like manager Bijoy) can override low-priority\n"
            "  commitments (like gym). The schedule_meeting tool handles this automatically.\n"
        )

    # ─── Time / day parsing helpers ───────────────────────────────────────────

    def _parse_time_str(self, time_str: str):
        """Parse natural time strings → datetime.time. Returns None if unparseable."""
        s = (time_str or "").strip().lower()

        word_map = {
            "morning": "09:00", "noon": "12:00", "afternoon": "14:00",
            "evening": "18:00", "night": "20:00", "tonight": "20:00", "midnight": "00:00"
        }
        for word, t in word_map.items():
            if word in s:
                return datetime.strptime(t, "%H:%M").time()

        # "20:00" or "8:30"
        m = re.match(r"^(\d{1,2}):(\d{2})$", s)
        if m:
            try:
                return datetime.strptime(f"{m.group(1)}:{m.group(2)}", "%H:%M").time()
            except ValueError:
                pass

        # "8pm", "8:30pm", "8 pm"
        m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", s)
        if m:
            h, mins = int(m.group(1)), int(m.group(2) or 0)
            if m.group(3) == "pm" and h != 12:
                h += 12
            if m.group(3) == "am" and h == 12:
                h = 0
            try:
                return datetime.strptime(f"{h:02d}:{mins:02d}", "%H:%M").time()
            except ValueError:
                pass

        # Plain number: assume PM for 1–6, AM for 7–11 (common convention)
        m = re.match(r"^(\d{1,2})$", s)
        if m:
            h = int(m.group(1))
            if 1 <= h <= 6:
                h += 12  # 1–6 → 13:00–18:00
            try:
                return datetime.strptime(f"{h:02d}:00", "%H:%M").time()
            except ValueError:
                pass

        return None

    def _parse_day_str(self, day_str: str) -> date:
        """Parse 'today', 'tomorrow', 'monday', etc. → date object."""
        s = (day_str or "today").strip().lower()
        today = date.today()
        if s in ("today", ""):
            return today
        if s == "tomorrow":
            return today + timedelta(days=1)
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        if s in day_names:
            target = day_names.index(s)
            current = today.weekday()
            delta = (target - current) % 7 or 7  # always forward
            return today + timedelta(days=delta)
        return today

    def _expand_day_shortcuts(self, days: list) -> list:
        """Expand 'weekdays', 'everyday', 'weekend' shortcuts."""
        result = []
        for d in days:
            s = d.lower()
            if s in ("weekdays", "weekday", "every weekday"):
                result += ["monday", "tuesday", "wednesday", "thursday", "friday"]
            elif s in ("everyday", "every day", "daily"):
                result += ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            elif s in ("weekend", "weekends"):
                result += ["saturday", "sunday"]
            else:
                result.append(s)
        return result

    # ─── Tool implementations ─────────────────────────────────────────────────

    def _tool_read_schedule(self, inp: dict) -> str:
        day_str = inp.get("day", "today")
        target = self._parse_day_str(day_str)
        day_enum = DayOfWeek(target.strftime("%A").lower())
        commitments = load_routine(self.routine_path)
        day_comms = sorted(
            [c for c in commitments if day_enum in c.days],
            key=lambda c: c.time_slot.start,
        )
        label = target.strftime("%A, %B %d")
        if not day_comms:
            return f"No commitments on {label} — completely free."
        lines = [f"Schedule for {label}:"]
        for c in day_comms:
            lock = " [cannot be moved]" if not c.reschedulable else ""
            lines.append(f"  • {c.time_slot.pretty():<25} {c.title}{lock} (priority {c.priority})")
        return "\n".join(lines)

    def _tool_check_time_slot(self, inp: dict) -> str:
        time_str = inp.get("time", "")
        duration = int(inp.get("duration_minutes", 60))
        day_str = inp.get("day", "today")

        start = self._parse_time_str(time_str)
        if start is None:
            return f"Couldn't parse time '{time_str}'. Use format like '8pm' or '20:00'."

        end_dt = datetime.combine(date.today(), start) + timedelta(minutes=duration)
        slot = TimeSlot(start=start, end=end_dt.time())
        target = self._parse_day_str(day_str)

        commitments = load_routine(self.routine_path)
        is_free, conflict = is_slot_free(target, slot, commitments)

        if is_free:
            return f"✅ {slot.pretty()} on {target.strftime('%A')} is free."
        return (
            f"❌ Conflict: '{conflict.title}' at {conflict.time_slot.pretty()} on {target.strftime('%A')}. "
            f"Priority: {conflict.priority}, moveable: {conflict.reschedulable}."
        )

    def _tool_get_free_slots(self, inp: dict) -> str:
        day_str = inp.get("day", "today")
        duration = int(inp.get("duration_minutes", 60))
        target = self._parse_day_str(day_str)
        commitments = load_routine(self.routine_path)
        slots = get_free_slots(target, commitments, duration_minutes=duration)
        if not slots:
            return f"No free {duration}-minute gaps on {target.strftime('%A, %B %d')}."
        pretty = [s.pretty() for s in slots[:6]]
        return f"Free {duration}-min slots on {target.strftime('%A, %B %d')}: {', '.join(pretty)}."

    def _tool_schedule_meeting(self, inp: dict) -> str:
        title = inp.get("title", "Meeting")
        time_str = inp.get("time", "")
        duration = int(inp.get("duration_minutes", 60))
        requester_id = inp.get("requester_id", "unknown")
        day_str = inp.get("day", "today")

        start = self._parse_time_str(time_str)
        if start is None:
            return f"Couldn't parse time '{time_str}'."

        end_dt = datetime.combine(date.today(), start) + timedelta(minutes=duration)
        slot = TimeSlot(start=start, end=end_dt.time())
        target = self._parse_day_str(day_str)

        request = MeetingRequest(
            requester_id=requester_id,
            requester_name=requester_id,
            channel="chat",
            message_text=title,
            requested_date=target,
            requested_time_slot=slot,
            duration_minutes=duration,
        )
        decision = handle_meeting_request(request, target, self.config, self.routine_path)

        # If approved, write it to routine
        if decision.action in ("confirm", "reschedule_and_confirm"):
            day_enum = DayOfWeek(target.strftime("%A").lower())
            new_c = Commitment(
                id=f"meeting-{title.lower().replace(' ', '-')}-{target}",
                title=title,
                commitment_type="work_meeting",
                days=[day_enum],
                time_slot=slot,
                priority=7,
                reschedulable=False,
                notes=f"Scheduled via assistant on {date.today()}",
            )
            existing = load_routine(self.routine_path)
            existing.append(new_c)
            save_routine(existing, self.routine_path)

        return (
            f"Action: {decision.action}. "
            f"{decision.reply_message} "
            f"(Reasoning: {decision.reasoning})"
        )

    def _tool_reschedule_commitment(self, inp: dict) -> str:
        title = inp.get("commitment_title", "")
        new_time_str = inp.get("new_time", "")

        commitments = load_routine(self.routine_path)
        match = next((c for c in commitments if c.title.lower() == title.lower()), None)
        if match is None:
            match = next((c for c in commitments if title.lower() in c.title.lower()), None)
        if match is None:
            names = ", ".join(c.title for c in commitments)
            return f"No commitment named '{title}'. Existing: {names}."

        new_start = self._parse_time_str(new_time_str)
        if new_start is None:
            return f"Couldn't parse new time '{new_time_str}'."

        old_pretty = match.time_slot.pretty()
        old_dur = match.time_slot.duration_minutes()
        end_dt = datetime.combine(date.today(), new_start) + timedelta(minutes=old_dur)
        match.time_slot = TimeSlot(start=new_start, end=end_dt.time())
        match.notes = f"Rescheduled from {old_pretty} via assistant."
        save_routine(commitments, self.routine_path)
        return f"Moved '{match.title}' from {old_pretty} to {match.time_slot.pretty()}."

    def _tool_cancel_commitment(self, inp: dict) -> str:
        title = inp.get("commitment_title", "")
        commitments = load_routine(self.routine_path)
        updated = [c for c in commitments if c.title.lower() != title.lower()]
        if len(updated) == len(commitments):
            updated = [c for c in commitments if title.lower() not in c.title.lower()]
        if len(updated) == len(commitments):
            names = ", ".join(c.title for c in commitments)
            return f"No commitment named '{title}'. Existing: {names}."
        removed = len(commitments) - len(updated)
        save_routine(updated, self.routine_path)
        return f"Removed {removed} commitment(s) matching '{title}'."

    def _tool_add_recurring_commitment(self, inp: dict) -> str:
        title = inp.get("title", "New Commitment")
        time_str = inp.get("time", "09:00")
        days_raw = self._expand_day_shortcuts(inp.get("days", ["monday"]))
        commitment_type = inp.get("commitment_type", "work_meeting")
        duration = int(inp.get("duration_minutes", 60))

        start = self._parse_time_str(time_str)
        if start is None:
            return f"Couldn't parse time '{time_str}'."

        day_enums = []
        for d in days_raw:
            try:
                day_enums.append(DayOfWeek(d.lower()))
            except ValueError:
                pass
        if not day_enums:
            return f"No valid days in {days_raw}. Use: monday, tuesday, ..., everyday, weekdays."

        end_dt = datetime.combine(date.today(), start) + timedelta(minutes=duration)
        cfg = self.config.get_commitment_config(commitment_type)
        new_c = Commitment(
            id=f"{title.lower().replace(' ', '-')}-recurring",
            title=title,
            commitment_type=commitment_type,
            days=day_enums,
            time_slot=TimeSlot(start=start, end=end_dt.time()),
            priority=cfg.get("priority", 5),
            reschedulable=cfg.get("reschedulable", True),
            notes=f"Added via assistant on {date.today()}",
        )
        existing = load_routine(self.routine_path)
        # Replace if same title exists, otherwise append
        existing = [c for c in existing if c.title.lower() != title.lower()]
        existing.append(new_c)
        save_routine(existing, self.routine_path)
        days_str = ", ".join(d.value for d in day_enums)
        return f"Added '{title}' every {days_str} at {new_c.time_slot.pretty()}."

    def _tool_send_slack_message(self, inp: dict) -> str:
        if self.slack is None or not self.slack.bot_token:
            return "Slack not configured — add SLACK_BOT_TOKEN to .env to enable it."
        channel = inp.get("channel", "meeting-times").lstrip("#")
        message = inp.get("message", "")
        if not message:
            return "No message provided."
        try:
            channel_id = self.slack.resolve_channel_id(channel)
            if not channel_id:
                for cid in (self.service_config.slack_channel_ids or []):
                    channel_id = self.slack.resolve_channel_id(cid)
                    if channel_id:
                        break
            if not channel_id:
                return f"Couldn't find Slack channel '{channel}'. Check the channel name."
            self.slack.send_message(channel_id, message)
            return f"✅ Sent to #{channel}: \"{message}\""
        except Exception as exc:
            return f"Slack error: {exc}"

    def _tool_send_email(self, inp: dict) -> str:
        import re as _re
        to_email = inp.get("to_email", "")
        subject = inp.get("subject", "Message from your assistant")
        context = inp.get("context", "")

        # Basic validation
        if not _re.match(r"[^@]+@[^@]+\.[^@]+", to_email):
            return f"Invalid email address: '{to_email}'"

        # Draft via Claude (using the existing email agent)
        from email_agent import EmailAgent
        agent = EmailAgent(model_name="claude-haiku-4-5-20251001")
        draft = agent.draft_email(to_email, subject, context)

        if self.google and self.google.creds:
            try:
                self.google.send_email(to_email, subject, draft)
                return f"✅ Email sent to {to_email}.\n\nSubject: {subject}\n\n{draft}"
            except Exception as exc:
                return (
                    f"Draft ready but send failed: {exc}\n\n"
                    f"Subject: {subject}\n\n{draft}"
                )
        return (
            f"Gmail not connected (add OAuth token.json). Draft ready to copy:\n\n"
            f"To: {to_email}\nSubject: {subject}\n\n{draft}"
        )

    # ─── Agent loop ───────────────────────────────────────────────────────────

    def _content_to_dicts(self, content) -> list:
        """Convert Anthropic SDK response blocks → plain dicts for history storage."""
        result = []
        for block in content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                result.append({"type": "text", "text": block.text})
            elif block_type == "tool_use":
                result.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        return result

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        """Dispatch a tool call to the right Python function."""
        dispatch = {
            "read_schedule":            self._tool_read_schedule,
            "check_time_slot":          self._tool_check_time_slot,
            "get_free_slots":           self._tool_get_free_slots,
            "schedule_meeting":         self._tool_schedule_meeting,
            "reschedule_commitment":    self._tool_reschedule_commitment,
            "cancel_commitment":        self._tool_cancel_commitment,
            "add_recurring_commitment": self._tool_add_recurring_commitment,
            "send_slack_message":       self._tool_send_slack_message,
            "send_email":               self._tool_send_email,
        }
        fn = dispatch.get(tool_name)
        if fn is None:
            return f"Unknown tool: {tool_name}"
        try:
            return str(fn(tool_input))
        except Exception as exc:
            return f"Tool '{tool_name}' error: {exc}"

    def respond(self, user_input: str) -> str:
        """
        Main entry point. Takes a user message, returns a natural language reply.

        Flow:
          1. Add message to history
          2. Call Claude with tool definitions
          3. If Claude wants to use a tool: execute it, feed result back, repeat
          4. When Claude has all info it needs: return the final text reply
        """
        if not user_input.strip():
            return "How can I help with your schedule today?"

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return (
                "⚠️  ANTHROPIC_API_KEY is not set. Add it to your .env file:\n"
                "  ANTHROPIC_API_KEY=sk-ant-..."
            )

        try:
            import anthropic as _anthropic
        except ImportError:
            return "anthropic package not installed. Run: pip install anthropic"

        client = _anthropic.Anthropic(api_key=api_key)

        # Add user message to history
        self.history.append({"role": "user", "content": user_input})

        # Trim history to keep context window manageable
        messages = self.history[-self.MAX_HISTORY:]

        model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

        # Tool-use agent loop (max 6 rounds before giving up)
        for _ in range(6):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=1024,
                    system=self._build_system_prompt(),
                    tools=TOOLS,
                    messages=messages,
                )
            except Exception as exc:
                return f"Claude API error: {exc}"

            if response.stop_reason == "end_turn":
                # Claude finished — extract text
                text = next(
                    (b.text for b in response.content if getattr(b, "type", "") == "text"),
                    "I couldn't generate a response. Please try again.",
                )
                assistant_dicts = self._content_to_dicts(response.content)
                self.history.append({"role": "assistant", "content": assistant_dicts})
                return text

            if response.stop_reason == "tool_use":
                # Claude wants to call tools
                assistant_dicts = self._content_to_dicts(response.content)
                messages.append({"role": "assistant", "content": assistant_dicts})
                self.history.append({"role": "assistant", "content": assistant_dicts})

                # Execute each tool Claude requested
                tool_results = []
                for block in response.content:
                    if getattr(block, "type", "") == "tool_use":
                        result = self._execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                # Feed results back
                messages.append({"role": "user", "content": tool_results})
                self.history.append({"role": "user", "content": tool_results})
                continue  # loop — Claude may call more tools or respond

            # Unexpected stop reason (e.g. max_tokens)
            break

        return "I ran into an issue processing that. Please try again."

    def clear_history(self):
        """Reset conversation context."""
        self.history = []

    def startup_check(self) -> str:
        """Status check — shown on app start."""
        lines = []
        if os.getenv("ANTHROPIC_API_KEY"):
            lines.append("✓ Claude API: configured")
        else:
            lines.append("✗ Claude API: ANTHROPIC_API_KEY not set (required)")

        if self.service_config.slack_enabled:
            if self.slack and self.slack.bot_token:
                lines.append("✓ Slack: configured")
            else:
                lines.append("○ Slack: SLACK_BOT_TOKEN not set")

        if self.service_config.gmail_enabled or self.service_config.calendar_enabled:
            if self.google and self.google.creds:
                lines.append("✓ Gmail/Calendar: authenticated")
            else:
                lines.append("○ Gmail/Calendar: token.json missing (run Google OAuth flow)")

        routine = load_routine(self.routine_path)
        lines.append(f"✓ Routine: {len(routine)} commitment(s) loaded")
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
