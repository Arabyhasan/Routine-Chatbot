from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

from availability import get_free_slots
from config_loader import Config
from email_agent import ClaudeAgent, IntentAgent, validate_email_address
from google_integration import GoogleIntegration
from knowledge_base import UserKnowledgeBase
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

    def __init__(self, config_path: str = "config.yaml", routine_path: str = "routine.json", service_config: ServiceConfig | None = None, knowledge_base_path: str = "knowledge_store.json"):
        project_root = Path(__file__).resolve().parent
        self.config = Config(str(project_root / config_path) if not Path(config_path).is_absolute() and not Path(config_path).exists() else config_path)
        self.routine_path = str(project_root / routine_path) if not Path(routine_path).is_absolute() and not Path(routine_path).exists() else routine_path
        self.knowledge_base = UserKnowledgeBase(str(project_root / knowledge_base_path) if not Path(knowledge_base_path).is_absolute() and not Path(knowledge_base_path).exists() else knowledge_base_path)
        self.service_config = service_config or ServiceConfig.from_env()
        self.slack = SlackIntegration() if self.service_config.slack_enabled else None
        self.google = GoogleIntegration() if self.service_config.gmail_enabled or self.service_config.calendar_enabled else None
        self.pending_change = None
        self.pending_email = None
        self.pending_send_target = None
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

    def _remember_user_context(self, user_input: str) -> None:
        """Store important preferences and reminders in the knowledge base."""
        if not user_input or not self.knowledge_base:
            return
        self.knowledge_base.remember_from_text(user_input)

    def _build_llm_context(self, user_input: str) -> str:
        """Create a single agent-style prompt so Gemini reasons across general chat, memory, and scheduling context."""
        routine = load_routine(self.routine_path)
        today_name = date.today().strftime("%A")
        summarized = []
        for item in routine[:8]:
            day_names = ", ".join(day.value for day in item.days) if getattr(item, "days", None) else "custom"
            summarized.append(f"- {item.title}: {day_names}, {item.time_slot.pretty()}")

        timeline = "\n".join(summarized) if summarized else "- No scheduled items yet."
        memory_lines = self.knowledge_base.get_memory_by_category() if self.knowledge_base else {}
        categorized_memory = []
        for category, items in memory_lines.items():
            if not items:
                continue
            listed = ", ".join(item["fact"] for item in items[:5])
            categorized_memory.append(f"{category.title()}: {listed}")
        memory_block = "\n".join(f"- {entry}" for entry in categorized_memory) if categorized_memory else "- No remembered preferences yet."
        profile_summary = self.knowledge_base.build_profile_summary() if self.knowledge_base else "No remembered user facts yet."
        return (
            "You are a helpful personal productivity assistant. "
            "Answer naturally, use the user's request as the top priority, and blend general conversation with schedule planning. "
            f"Today is {today_name}. The user's current routine is:\n{timeline}\n\n"
            f"User profile summary:\n{profile_summary}\n\n"
            f"Remembered user facts by category:\n{memory_block}\n\n"
            "You may help with: general conversation, routine questions, meeting planning, email drafting, and task scheduling. "
            "If the user asks to schedule or modify a meeting, keep the response brief, clear, and actionable. "
            "Do not mention internal system details.\n\nUser request: "
            f"{user_input}"
        )

    def _resolve_gemini_model(self) -> str:
        """Pick a supported Gemini model name from the current API surface."""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return ""

        candidates = [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
        ]

        for model in candidates:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                probe = requests.post(
                    url,
                    json={"contents": [{"parts": [{"text": "Return exactly: MODEL_OK"}]}]},
                    timeout=20,
                )
                if probe.status_code == 200:
                    return model
            except Exception:
                continue
        return candidates[0]

    def _llm_chat_response(self, user_input: str) -> str:
        """Use Gemini for real reasoning across both general chat and scheduling tasks."""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return ""

        model_name = self._resolve_gemini_model()
        if not model_name:
            return ""

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        prompt = self._build_llm_context(user_input)
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
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

    def _extract_json_from_model_text(self, text: str):
        if not text:
            return None
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None

    def _llm_classify_user_action(self, text: str) -> dict:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {"action": "general_chat"}

        prompt = (
            "Classify the user's intent. Return only valid JSON with the shape {\"action\": \"send_email\"|\"send_slack_message\"|\"schedule_meeting\"|\"general_chat\"|\"check_routine\"}. "
            "Use 'send_slack_message' when the user wants to send a direct message or post a message in Slack, even if the text contains a time like '8am'. "
            "Use 'schedule_meeting' only when the user is actually asking to arrange, book, or confirm a meeting or call. "
            "Examples: 'send a dm to slack meeting at 8 am' => send_slack_message; 'can we meet at 8am?' => schedule_meeting; 'send email to jane@example.com' => send_email; 'show my routine' => check_routine. "
            f"Message: {text}"
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._resolve_gemini_model() or 'gemini-2.0-flash'}:generateContent?key={api_key}"
        try:
            response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            if response.status_code != 200:
                return {"action": "general_chat"}
            payload = response.json()
            for candidate in payload.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    parsed = self._extract_json_from_model_text(part.get("text", ""))
                    if isinstance(parsed, dict) and "action" in parsed:
                        action = str(parsed["action"]).strip().lower()
                        if action in {"send_email", "send_slack_message", "schedule_meeting", "general_chat", "check_routine"}:
                            return {"action": action}
        except Exception:
            return {"action": "general_chat"}
        return {"action": "general_chat"}

    def _llm_classify_meeting_request(self, text: str) -> bool:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return False

        prompt = (
            "Decide whether this message is a meeting or scheduling request. "
            "Return only valid JSON: {\"is_meeting_request\": true|false}. "
            "Examples of true: 'can we meet', 'schedule a call', 'book a meeting', 'I am free tomorrow at 3pm'. "
            "Examples of false: 'how are you', 'what's up', 'tell me about my routine'. "
            f"Message: {text}"
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._resolve_gemini_model() or 'gemini-2.0-flash'}:generateContent?key={api_key}"
        try:
            response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            if response.status_code != 200:
                return False
            payload = response.json()
            for candidate in payload.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    value = part.get("text", "")
                    parsed = self._extract_json_from_model_text(value)
                    if not isinstance(parsed, dict):
                        continue
                    if "is_meeting_request" in parsed:
                        return bool(parsed.get("is_meeting_request"))
                    if "meeting_request" in parsed:
                        return bool(parsed.get("meeting_request"))
        except Exception:
            return False
        return False

    def _looks_like_meeting_request(self, text: str) -> bool:
        lower = (text or "").lower()
        meeting_words = [
            "meeting",
            "meet",
            "schedule",
            "arrange",
            "sync",
            "call",
            "chat",
            "coffee",
            "availability",
            "free for",
            "free at",
            "can we meet",
            "let's meet",
        ]
        if any(word in lower for word in meeting_words):
            return True
        if re.search(r"\b(?:meet|meeting|schedule|arrange|sync|call)\b", lower):
            return True
        return self._llm_classify_meeting_request(text)

    def _extract_relative_date(self, text: str):
        lower = text.lower()
        today = date.today()
        if "tomorrow" in lower:
            return today.replace(day=today.day + 1) if today.day < 28 else today
        if "today" in lower or "tonight" in lower or "this evening" in lower:
            return today
        return today

    def _llm_extract_meeting_time(self, text: str):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None

        prompt = (
            "Extract the meeting time and date from this message. "
            "Return only a JSON object like {\"date\": \"YYYY-MM-DD\", \"time\": \"HH:MM\"}. "
            "Interpret natural language like 'at 8 at night today', 'tomorrow at 9am', 'this evening', 'morning', 'afternoon', 'night'. "
            f"Message: {text}"
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        try:
            response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            if response.status_code != 200:
                return None
            payload = response.json()
            for candidate in payload.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    text_value = part.get("text", "")
                    if not text_value:
                        continue
                    match = re.search(r"\{.*\}", text_value, re.S)
                    if match:
                        import json as json_mod
                        return json_mod.loads(match.group(0))
        except Exception:
            return None
        return None

    def _parse_time_from_text(self, text: str):
        lower = text.lower()

        time_hint = None
        if any(word in lower for word in ["at night", "night", "tonight", "this evening", "evening"]):
            time_hint = datetime.strptime("20:00", "%H:%M").time()
        elif any(word in lower for word in ["morning", "in the morning", "tomorrow morning"]):
            time_hint = datetime.strptime("09:00", "%H:%M").time()
        elif "afternoon" in lower:
            time_hint = datetime.strptime("15:00", "%H:%M").time()
        elif "noon" in lower:
            time_hint = datetime.strptime("12:00", "%H:%M").time()

        if time_hint is not None:
            end = datetime.strptime(f"{time_hint.hour + 1:02d}:{time_hint.minute:02d}", "%H:%M").time()
            return TimeSlot(start=time_hint, end=end)

        explicit_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.IGNORECASE)
        if explicit_match:
            hour = int(explicit_match.group(1))
            minute = int(explicit_match.group(2) or 0)
            meridiem = (explicit_match.group(3) or "").lower()
            if meridiem == "pm" and hour < 12:
                hour += 12
            if meridiem == "am" and hour == 12:
                hour = 0
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                start = datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()
                end_minute = minute + 60
                end_hour = hour
                if end_minute >= 60:
                    end_hour += 1
                    end_minute -= 60
                end = datetime.strptime(f"{end_hour:02d}:{end_minute:02d}", "%H:%M").time()
                return TimeSlot(start=start, end=end)

        llm_data = self._llm_extract_meeting_time(text)
        if llm_data and llm_data.get("time"):
            try:
                parsed_time = datetime.strptime(llm_data["time"], "%H:%M").time()
                end = datetime.strptime(f"{parsed_time.hour + 1:02d}:{parsed_time.minute:02d}", "%H:%M").time()
                return TimeSlot(start=parsed_time, end=end)
            except ValueError:
                return None

        return None

    def _match_commitment_by_time(self, text: str):
        target_time = self._parse_time_from_text(text)
        if target_time is None:
            return None
        for commitment in self._today_commitments():
            if commitment.time_slot.start.hour == target_time.start.hour and commitment.time_slot.start.minute == target_time.start.minute:
                return commitment
        return None

    def _extract_send_target(self, text: str) -> str | None:
        lower = (text or "").lower()

        if re.search(r"\bcancel\s+mail\s+and\s+send\s+(?:a\s+)?dm\b", lower):
            return "dm"

        send_match = re.search(r"\bsend\b(?:\s+\w+){0,6}\s+(mail|dm)\b", lower)
        if send_match:
            return send_match.group(1)
        return None

    def _is_exact_mail_to_dm_override(self, text: str) -> bool:
        return bool(re.search(r"\bcancel\s+mail\s+and\s+send\s+(?:a\s+)?dm\b", (text or "").lower()))

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
        self.pending_send_target = None
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

        email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        intent = self.intent_agent.parse(text)
        if intent.get("intent") != "email" and not email_match:
            return ""

        email = intent.get("to_email") or (email_match.group(0) if email_match else None)
        if not email or not validate_email_address(email):
            return "I need a valid email address before I can draft or send an email."

        cleaned = text.strip()
        if email_match:
            cleaned = cleaned.replace(email_match.group(0), "").strip()
        cleaned = re.sub(r"^(send|draft|write)\s+email\s+to\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(send|draft|write)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(email|mail)\s+to\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" -:;,. ")
        if not cleaned:
            cleaned = "Please review the attached details and let me know your availability."

        subject_hint = "Meeting request"
        lowered = cleaned.lower()
        if "budget" in lowered:
            subject_hint = "Quarterly budget review"
        elif "availability" in lowered or "free" in lowered:
            subject_hint = "Availability and next steps"
        elif "follow up" in lowered or "review" in lowered:
            subject_hint = "Follow-up and review"
        elif "thank" in lowered:
            subject_hint = "Thank you"
        elif "schedule" in lowered or "meeting" in lowered:
            subject_hint = "Meeting request"

        draft = self.email_agent.draft_email(email, subject_hint, cleaned)
        self.pending_email = {"to_email": email, "subject": subject_hint, "body": draft}
        self.pending_send_target = "mail"
        return (
            f"Draft ready for {email}:\n\n"
            f"Subject: {subject_hint}\n\n{draft}\n\n"
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

    def _handle_slack_send_message(self, text: str) -> str | None:
        lower_text = text.lower()
        if self.slack is None:
            return None

        has_send_intent = any(keyword in lower_text for keyword in [
            "send a dm", "send a message", "send dm", "dm to slack", "message to slack",
            "post to slack", "send to slack", "message in slack", "to slack saying",
            "to slack say", "post to #meeting-times", "send a message to #meeting-times",
            "send a dm to slack", "send dm to slack", "send a message to slack", "send message to slack",
        ])
        has_channel_target = "meeting-times" in lower_text or "#meeting-times" in lower_text or "meeting times" in lower_text
        if not (has_send_intent or has_channel_target):
            return None
        if any(phrase in lower_text for phrase in ["can we meet", "schedule a meeting", "arrange a meeting", "let's meet", "meeting request", "book a meeting"]):
            return None

        target = "meeting-times"
        for candidate in ["meeting-times", "#meeting-times", "meeting times"]:
            if candidate in lower_text:
                target = candidate
                break

        message = text
        if "saying" in lower_text:
            _, message = text.split("saying", 1)
            message = message.strip().strip('"\'')
        elif "say " in lower_text:
            _, message = re.split(r"\bsay\b", text, flags=re.IGNORECASE, maxsplit=1)
            message = message.strip().strip('"\'')
        else:
            message = re.sub(r"^(?:send|dm|message|post)\s+(?:a\s+)?(?:dm\s+)?(?:to\s+)?(?:slack\s+)?(?:in\s+)?(?:channel\s+)?(?:to\s+)?(?:#?meeting-times\s+)?", "", text, flags=re.IGNORECASE).strip()
            message = re.sub(r"^(?:saying\s+|say\s+)", "", message, flags=re.IGNORECASE).strip()

        if not message:
            message = "Meeting at 8 am"
        elif message and message[0].islower():
            message = message[0].upper() + message[1:]

        channel_id = getattr(self.slack, "resolve_channel_id", lambda _target: None)(target)
        if not channel_id:
            for candidate in self.service_config.slack_channel_ids or ["meeting-times"]:
                channel_id = getattr(self.slack, "resolve_channel_id", lambda _target: None)(candidate)
                if channel_id:
                    break
        if not channel_id:
            return "I couldn't find the Slack meeting-times channel, so I couldn't send the message."

        self.pending_send_target = "dm"
        self.slack.send_message(channel_id, message)
        self.pending_send_target = None
        return f"Slack message sent to {target}."

    def respond(self, user_input: str) -> str:
        text = (user_input or "").strip()
        lower_text = text.lower()

        self._remember_user_context(text)

        explicit_send_target = self._extract_send_target(text)
        if self._is_exact_mail_to_dm_override(text):
            self.pending_email = None
            self.pending_send_target = "dm"
        elif explicit_send_target == "mail":
            self.pending_send_target = "mail"
        elif explicit_send_target == "dm":
            self.pending_send_target = "dm"

        if self.pending_email and self.pending_send_target == "mail":
            if not re.search(r"\bsend\b(?:\s+\w+){0,6}\s+(?:mail|dm)\b", lower_text):
                email_response = self._handle_email(text)
                if email_response and email_response.strip():
                    return email_response

        llm_action = self._llm_classify_user_action(text)
        if llm_action.get("action") == "send_slack_message":
            slack_send_response = self._handle_slack_send_message(text)
            if slack_send_response:
                return slack_send_response

        if llm_action.get("action") == "send_email":
            email_response = self._handle_email(text)
            if email_response and email_response.strip():
                return email_response

        if llm_action.get("action") == "schedule_meeting":
            if self._looks_like_meeting_request(lower_text):
                day = date.today()
                requested_time = self._parse_time_from_text(lower_text)
                if requested_time is None:
                    return "I can help schedule that. Tell me the time and date more clearly, and I’ll confirm the slot."
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

        slack_send_response = self._handle_slack_send_message(text)
        if slack_send_response:
            return slack_send_response

        recurring_response = self._handle_recurring_commitment(text)
        if recurring_response:
            return recurring_response

        if self.pending_email and any(keyword in lower_text for keyword in ["confirm", "cancel", "yes", "no", "send it", "send", "approve", "reject"]):
            email_response = self._handle_email(text)
            if email_response:
                return email_response

        if self.pending_email and not any(keyword in lower_text for keyword in ["confirm", "cancel", "yes", "no", "send it", "send", "approve", "reject", "email", "draft"]):
            self.pending_email = None

        if not text:
            return "I can help with your routine. Ask: 'When am I free today?', 'Can we meet at 8pm?', or 'Show my schedule.'"

        if any(word in lower_text for word in ["#general", "slack", "channel"]) or self._looks_like_meeting_request(lower_text):
            if self._looks_like_meeting_request(lower_text):
                day = date.today()
                requested_time = self._parse_time_from_text(lower_text)
                if requested_time is None:
                    return "I can help schedule that. Tell me the time and date more clearly, and I’ll confirm the slot."
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

        email_response = self._handle_email(text)
        if email_response and email_response.strip():
            return email_response

        provider_response = self._llm_chat_response(text)
        if provider_response and provider_response.strip():
            return provider_response.strip()

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

        if self._looks_like_meeting_request(lower_text):
            day = date.today()
            requested_time = self._parse_time_from_text(lower_text)
            if not requested_time:
                return "I can help schedule that. Tell me the time and date more clearly, and I’ll confirm the slot."
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
