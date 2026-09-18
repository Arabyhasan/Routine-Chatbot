from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

import requests

from availability import get_free_slots
from config_loader import Config
from email_agent import ClaudeAgent, IntentAgent, validate_email_address
from google_integration import GoogleIntegration
from models import DayOfWeek, MeetingRequest, TimeSlot
from priority import handle_meeting_request
from routine_manager import load_routine, save_routine
from service_config import ServiceConfig, prompt_service_selection
from slack_integration import SlackIntegration


class MCPToolClient:
    """Minimal MCP client wrapper for the local FastMCP server."""

    def __init__(self, server_path: str = "mcp_server.py"):
        self.server_path = server_path
        self._client = None

    def _ensure_initialized(self):
        if self._client is not None:
            return self._client

        try:
            from mcp import ClientSession
            from mcp.client.stdio import stdio_client, StdioServerParameters

            params = StdioServerParameters(command="python", args=[self.server_path], env=None)
            self._client = {"session": None, "params": params}
        except Exception:
            self._client = {"session": None, "params": None}
        return self._client

    def get_routine_summary(self):
        try:
            if self._ensure_initialized()["params"] is None:
                return None
            from mcp import ClientSession
            from mcp.client.stdio import stdio_client

            async def _runner():
                async with stdio_client(self._ensure_initialized()["params"]) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool("get_routine_summary", {})
                        return result

            import asyncio
            return asyncio.run(_runner())
        except Exception:
            return None

    def get_free_slots_for_today(self):
        try:
            if self._ensure_initialized()["params"] is None:
                return None
            from mcp import ClientSession
            from mcp.client.stdio import stdio_client

            async def _runner():
                async with stdio_client(self._ensure_initialized()["params"]) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool("get_free_slots_for_today", {})
                        return result

            import asyncio
            return asyncio.run(_runner())
        except Exception:
            return None


class RoutineChatbot:
    """Interactive routine assistant with service selection and meeting rescheduling."""

    def __init__(self, config_path: str = "config.yaml", routine_path: str = "routine.json", service_config: ServiceConfig | None = None):
        self.config = Config(config_path)
        self.routine_path = routine_path
        self.service_config = service_config or ServiceConfig.from_env()
        self.slack = SlackIntegration() if self.service_config.slack_enabled else None
        self.google = GoogleIntegration() if self.service_config.gmail_enabled or self.service_config.calendar_enabled else None
        self.pending_change = None
        self.pending_email = None
        self.intent_agent = IntentAgent()
        self.email_agent = ClaudeAgent()
        self.mcp_client = MCPToolClient()

    def _mcp_routine_summary(self):
        if hasattr(self, "mcp_client") and self.mcp_client is not None:
            result = self.mcp_client.get_routine_summary()
            if result is not None:
                if hasattr(result, "content"):
                    pieces = []
                    for item in result.content:
                        if getattr(item, "type", "") == "text":
                            pieces.append(item.text)
                    if pieces:
                        return "\n".join(pieces)
                if isinstance(result, str):
                    return result
        return None

    def _mcp_free_slots(self):
        if hasattr(self, "mcp_client") and self.mcp_client is not None:
            result = self.mcp_client.get_free_slots_for_today()
            if result is not None:
                if hasattr(result, "content"):
                    items = []
                    for item in result.content:
                        if getattr(item, "type", "") == "text":
                            items.append(item.text)
                    if items:
                        return items
                if isinstance(result, list):
                    return result
        return None

    def _llm_chat_response(self, user_input: str) -> str:
        """Use Gemini for all live reasoning and text generation.

        This project is intentionally configured for Gemini-only runtime behavior,
        while still keeping the project logic as a fallback path when no key exists.
        """
        provider = "gemini"
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return ""

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": user_input}]}]}
        try:
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code != 200:
                return ""
            data = response.json()
            candidates = data.get("candidates") or []
            for cand in candidates:
                parts = cand.get("content", {}).get("parts", [])
                for part in parts:
                    if isinstance(part, dict) and "text" in part:
                        return part["text"]
            return ""
        except Exception:
            return ""

    def startup_check(self) -> str:
        lines = [
            f"Service mode: {', '.join(self.service_config.enabled_services) if self.service_config.enabled_services else 'none'}",
        ]
        if self.service_config.slack_enabled:
            if self.slack and self.slack.bot_token:
                lines.append("Slack: authenticated and ready.")
            else:
                lines.append("Slack: not configured. Add SLACK_BOT_TOKEN in .env to enable it.")
        if self.service_config.gmail_enabled or self.service_config.calendar_enabled:
            if self.google and self.google.creds is not None:
                lines.append("Gmail/Calendar: authenticated and ready.")
            else:
                lines.append("Gmail/Calendar: OAuth token missing. Add token.json or run the Google login flow.")
        routine = load_routine(self.routine_path)
        if routine:
            lines.append(f"Loaded routine: {len(routine)} commitment(s).")
        else:
            lines.append("No routine is loaded yet. Your schedule is empty for today.")
        return "\n".join(lines)

    def _today_commitments(self):
        commitments = load_routine(self.routine_path)
        today_name = date.today().strftime("%A").lower()
        day_enum = DayOfWeek(today_name)
        return [c for c in commitments if day_enum in c.days]

    def _parse_time_from_text(self, text: str):
        match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.IGNORECASE)
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = (match.group(3) or "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        start = datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()
        end_minute = minute + 60
        end_hour = hour
        if end_minute >= 60:
            end_hour += 1
            end_minute -= 60
        end = datetime.strptime(f"{end_hour:02d}:{end_minute:02d}", "%H:%M").time()
        return TimeSlot(start=start, end=end)

    def _match_commitment_by_time(self, text: str):
        target_time = self._parse_time_from_text(text)
        if target_time is None:
            return None
        for commitment in self._today_commitments():
            if commitment.time_slot.start.hour == target_time.start.hour and commitment.time_slot.start.minute == target_time.start.minute:
                return commitment
        return None

    def _handle_reschedule(self, text: str) -> str:
        lower = text.lower()

        if self.pending_change and any(word in lower for word in ["confirm", "yes", "approve", "ok"]):
            original = self.pending_change["original"]
            new_time = self.pending_change["new_time"]
            commitments = load_routine(self.routine_path)
            updated = []
            for c in commitments:
                if c.id == original.id:
                    c.time_slot.start = new_time
                    end_hour = new_time.hour + 1
                    end_minute = new_time.minute
                    if end_minute >= 60:
                        end_hour += 1
                        end_minute -= 60
                    c.time_slot.end = datetime.strptime(f"{end_hour:02d}:{end_minute:02d}", "%H:%M").time()
                    c.notes = f"Rescheduled by assistant. Original time: {self.pending_change['old_time']}"
                updated.append(c)
            save_routine(updated, self.routine_path)
            self.pending_change = None
            return f"Confirmed. I updated your routine and moved {original.title} to {new_time.strftime('%I:%M %p')}."

        if self.pending_change and any(word in lower for word in ["cancel", "no", "reject"]):
            self.pending_change = None
            return "Reschedule request cancelled. Your routine remains unchanged."

        if any(word in lower for word in ["cancel", "move", "reschedule", "postpone"]):
            target = self._match_commitment_by_time(text)
            if target is None:
                return "I couldn't find a meeting at that time in your routine. Please specify an exact time like '9 pm' or '10:30 pm'."

            new_match = re.search(r"(?:to|at|for)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.IGNORECASE)
            if not new_match:
                return (
                    f"I found {target.title} at {target.time_slot.pretty()}. "
                    f"If you want to move it, tell me the new time, for example: 'move {target.title} to 10 pm'."
                )

            new_hour = int(new_match.group(1))
            new_minute = int(new_match.group(2) or 0)
            meridiem = (new_match.group(3) or "").lower()
            if meridiem == "pm" and new_hour < 12:
                new_hour += 12
            if meridiem == "am" and new_hour == 12:
                new_hour = 0
            new_time = datetime.strptime(f"{new_hour:02d}:{new_minute:02d}", "%H:%M").time()
            self.pending_change = {
                "original": target,
                "new_time": new_time,
                "old_time": target.time_slot.pretty(),
            }
            return (
                f"I’ve requested the change for {target.title}. "
                f"I can move it from {target.time_slot.pretty()} to {new_time.strftime('%I:%M %p')}. "
                f"Reply 'confirm' or 'cancel'."
            )

        return ""

    def _send_pending_email(self) -> str:
        pending = self.pending_email
        self.pending_email = None
        if not pending:
            return "There is no pending email draft."
        if self.google is None or self.google.creds is None:
            return (
                f"I have the draft ready for {pending['to_email']}, but Gmail isn't connected yet, so nothing was sent. "
                "Please authenticate Google before sending email."
            )
        try:
            self.google.send_email(pending["to_email"], pending["subject"], pending["body"])
            return f"Email sent to {pending['to_email']} with subject \"{pending['subject']}\"."
        except Exception as exc:
            return f"I tried to send the email to {pending['to_email']}, but it failed: {exc}"

    def _handle_email(self, text: str) -> str:
        lower = text.lower()
        if self.pending_email:
            if any(word in lower for word in ["confirm", "yes", "approve", "ok"]):
                return self._send_pending_email()
            if any(word in lower for word in ["cancel", "no", "reject"]):
                self.pending_email = None
                return "Okay, I won’t send that email."
            if "send it" in lower or "send" in lower:
                pending = self.pending_email
                return (
                    f"Draft ready for {pending['to_email']}:\n\n"
                    f"Subject: {pending['subject']}\n\n{pending['body']}\n\n"
                    "Reply 'confirm' to send it, or 'cancel' to stop."
                )
            pending = self.pending_email
            return (
                f"Draft ready for {pending['to_email']}:\n\n"
                f"Subject: {pending['subject']}\n\n{pending['body']}\n\n"
                "Reply 'confirm' to send it, or 'cancel' to stop."
            )

        intent = self.intent_agent.parse(text)
        if intent.get("intent") != "email":
            return ""

        email = intent.get("to_email")
        if not email or not validate_email_address(email):
            return "I need a valid email address before I can draft or send an email."

        draft = self.email_agent.draft_email(
            email,
            "Meeting request",
            "I am reaching out to ask for a good time to connect. Please let me know when you are free.",
        )
        self.pending_email = {"to_email": email, "subject": "Meeting request", "body": draft}
        return (
            f"Claude draft ready for {email}:\n\n{draft}\n\n"
            "Reply 'confirm' to send it, or 'cancel' to stop."
        )

    def _handle_recurring_commitment(self, text: str) -> str | None:
        from message_parser import parse_recurring_commitment_text

        parsed = parse_recurring_commitment_text(text)
        if not parsed:
            return None

        commitments = load_routine(self.routine_path)
        existing = [c for c in commitments if c.title.lower() == parsed["title"].lower()]
        if existing:
            for item in existing:
                item.days = parsed["days"]
                item.time_slot.start = datetime.strptime(parsed["start_time"], "%H:%M").time()
                item.time_slot.end = datetime.strptime(parsed["end_time"], "%H:%M").time()
                item.notes = f"Updated from recurring instruction: {text}"
            save_routine(commitments, self.routine_path)
            return f"Updated your {parsed['title']} schedule to {parsed['start_time']} every day except Friday."

        from models import Commitment, TimeSlot
        commitment = Commitment(
            id=f"{parsed['title'].lower()}-{len(commitments) + 1}",
            title=parsed["title"],
            commitment_type=parsed["title"].lower().replace(" ", "_"),
            days=parsed["days"],
            time_slot=TimeSlot(
                start=datetime.strptime(parsed["start_time"], "%H:%M").time(),
                end=datetime.strptime(parsed["end_time"], "%H:%M").time(),
            ),
            priority=2,
            reschedulable=True,
            notes=f"Added from recurring instruction: {text}",
        )
        commitments.append(commitment)
        save_routine(commitments, self.routine_path)
        return f"Added {parsed['title']} at {parsed['start_time']} for the recurring days you described."

    def respond(self, user_input: str) -> str:
        text = (user_input or "").strip()
        lower_text = text.lower()

        recurring_response = self._handle_recurring_commitment(text)
        if recurring_response:
            return recurring_response

        if self.pending_email:
            email_response = self._handle_email(text)
            if email_response:
                return email_response

        if not text:
            return "I can help with your routine. Ask: 'When am I free today?', 'Can we meet at 8pm?', or 'Show my schedule.'"

        if any(word in lower_text for word in ["#general", "slack", "channel"]):
            if "can we meet" in lower_text or "meet at" in lower_text or "meeting" in lower_text:
                day = date.today()
                requested_time = self._parse_time_from_text(lower_text)
                if requested_time is None:
                    return "I can schedule it in the channel. Please include a time like '8pm' or '7:30 PM', and I’ll confirm the slot."
                request = MeetingRequest(
                    requester_id="bijoy",
                    requester_name="Bijoy",
                    channel="slack",
                    message_text=user_input,
                    requested_date=day,
                    requested_time_slot=requested_time,
                    duration_minutes=60,
                )
                decision = handle_meeting_request(request, day, self.config, self.routine_path)
                if decision.action in {"confirm", "reschedule_and_confirm"}:
                    return f"{decision.reply_message} Reply 'confirm' in the channel to lock it in, or 'cancel' to stop."
                return decision.reply_message

        provider_response = self._llm_chat_response(text)
        if provider_response and provider_response.strip():
            return provider_response.strip()

        email_response = self._handle_email(text)
        if email_response and email_response.strip():
            return email_response

        pending_response = self._handle_reschedule(text)
        if pending_response:
            return pending_response

        mcp_summary = self._mcp_routine_summary()
        if mcp_summary and ("when am i free" in lower_text or "free today" in lower_text):
            free_slots = self._mcp_free_slots()
            if free_slots:
                return f"Your next free slots today are: {', '.join(free_slots)}."

        if "when am i free" in lower_text or "free today" in lower_text:
            today = date.today()
            commitments = load_routine(self.routine_path)
            slots = get_free_slots(today, commitments, duration_minutes=60)
            if not slots:
                return "You do not have any free 60-minute blocks today based on your current routine."
            readable = ", ".join(slot.pretty() for slot in slots[:5])
            return f"Your next free slots today are: {readable}."

        if any(keyword in lower_text for keyword in ["show my schedule", "show my routine", "schedule", "routine", "what's my routine", "what is my routine"]):
            commitments = self._today_commitments()
            if not commitments:
                return "You have no meetings scheduled for today. Your routine is empty right now."
            summary = ", ".join(f"{c.title} at {c.time_slot.pretty()}" for c in commitments)
            return f"Your routine for today: {summary}."

        if "can we meet" in lower_text or "meet at" in lower_text or "meeting" in lower_text:
            day = date.today()
            requested_time = self._parse_time_from_text(lower_text)
            if not requested_time:
                return "I can help schedule a meeting. Please include a time like '8pm' or '7:30 PM'."
            request = MeetingRequest(
                requester_id="bijoy",
                requester_name="Bijoy",
                channel="slack",
                message_text=user_input,
                requested_date=day,
                requested_time_slot=requested_time,
                duration_minutes=60,
            )
            decision = handle_meeting_request(request, day, self.config, self.routine_path)
            return decision.reply_message

        if any(word in lower_text for word in ["cancel", "move", "reschedule", "postpone"]):
            return self._handle_reschedule(text)

        return (
            "I can help with routine planning. Try asking: 'When am I free today?', "
            "'Show my schedule', 'What's my routine today?', or 'Can we meet at 8pm?'"
        )


def main():
    service_config = prompt_service_selection()
    bot = RoutineChatbot(service_config=service_config)
    print(bot.startup_check())
    print("\nRoutine Agent demo. Type 'exit' to quit.")
    while True:
        try:
            prompt = input("You: ")
        except KeyboardInterrupt:
            print("\nGoodbye.")
            break
        if prompt.strip().lower() in {"exit", "quit"}:
            print("Goodbye.")
            break
        print(f"Agent: {bot.respond(prompt)}")


if __name__ == "__main__":
    main()
