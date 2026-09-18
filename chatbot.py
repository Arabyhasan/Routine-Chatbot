from __future__ import annotations

from datetime import date, datetime
from typing import List

from availability import get_free_slots, summarize_day
from config_loader import Config
from models import MeetingRequest, TimeSlot
from priority import handle_meeting_request
from routine_manager import load_routine, get_commitments_for_day


class RoutineChatbot:
    """Simple terminal chatbot demo for the Routine Agent."""

    def __init__(self, config_path: str = "config.yaml", routine_path: str = "routine.json"):
        self.config = Config(config_path)
        self.routine_path = routine_path

    def respond(self, user_input: str) -> str:
        text = (user_input or "").strip().lower()

        if not text:
            return "I can help with your routine. Ask: 'When am I free today?', 'Can we meet at 8pm?', or 'Show my schedule.'"

        if "when am i free" in text or "free today" in text:
            today = date.today()
            commitments = load_routine(self.routine_path)
            slots = get_free_slots(today, commitments, duration_minutes=60)
            if not slots:
                return "You do not have any free 60-minute blocks today based on your current routine."
            readable = ", ".join(slot.pretty() for slot in slots[:5])
            return f"Your next free slots today are: {readable}."

        if "show my schedule" in text or "schedule" in text or "routine" in text:
            today = date.today()
            commitments = load_routine(self.routine_path)
            return summarize_day(today, commitments)

        if "can we meet" in text or "meet at" in text or "meeting" in text:
            day = date.today()
            requested_time = self._parse_time_from_text(text)
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

        return (
            "I can help with routine planning. Try asking: 'When am I free today?', "
            "'Show my schedule', or 'Can we meet at 8pm?'"
        )

    def _parse_time_from_text(self, text: str):
        # Basic parser for common time strings in demo mode.
        import re

        match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
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

        return TimeSlot(start=datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time(),
                        end=datetime.strptime(f"{hour:02d}:{minute+60 if minute > 0 else 60:02d}", "%H:%M").time())


def main():
    bot = RoutineChatbot()
    print("Routine Agent demo. Type 'exit' to quit.")
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
