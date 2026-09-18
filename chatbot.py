from __future__ import annotations

import re
from datetime import date, datetime

from availability import get_free_slots
from config_loader import Config
from email_agent import ClaudeAgent, IntentAgent, validate_email_address
from google_integration import GoogleIntegration
from models import DayOfWeek, MeetingRequest, TimeSlot
from priority import handle_meeting_request
from routine_manager import load_routine, save_routine
from service_config import ServiceConfig, prompt_service_selection
from slack_integration import SlackIntegration


class RoutineChatbot:
    """Interactive routine assistant with service selection and meeting rescheduling."""

    def __init__(self, config_path: str = "config.yaml", routine_path: str = "routine.json", service_config: ServiceConfig | None = None):
        self.config = Config(config_path)
        self.routine_path = routine_path
        self.service_config = service_config or ServiceConfig.from_env()
        self.slack = SlackIntegration() if self.service_config.slack_enabled else None
        self.google = GoogleIntegration() if self.service_config.gmail_enabled or self.service_config.calendar_enabled else None
        self.pending_change = None
        self.intent_agent = IntentAgent()
        self.email_agent = ClaudeAgent()

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

    def respond(self, user_input: str) -> str:
        text = (user_input or "").strip()
        lower_text = text.lower()

        intent = self.intent_agent.parse(text)
        if intent.get("intent") == "email":
            email = intent.get("to_email")
            if not email or not validate_email_address(email):
                return "I need a valid email address before I can draft or send an email."
            draft = self.email_agent.draft_email(
                email,
                "Meeting request",
                f"I am reaching out to ask for a good time to connect. Please let me know when you are free.",
            )
            return f"Claude model draft for {email}:\n\n{draft}"

        pending_response = self._handle_reschedule(text)
        if pending_response:
            return pending_response

        if not text:
            return "I can help with your routine. Ask: 'When am I free today?', 'Can we meet at 8pm?', or 'Show my schedule.'"

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
