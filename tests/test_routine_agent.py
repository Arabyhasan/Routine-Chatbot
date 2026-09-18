from datetime import date

from config_loader import Config
from models import MeetingRequest, TimeSlot
from priority import handle_meeting_request
from chatbot import RoutineChatbot


def test_manager_override_reschedules_low_priority_commitment():
    config = Config("config.yaml")
    request = MeetingRequest(
        requester_id="bijoy",
        requester_name="Bijoy",
        channel="slack",
        message_text="Can we meet at 8:00 PM today?",
        requested_date=date(2026, 9, 18),
        requested_time_slot=TimeSlot(start=(__import__("datetime").time(20, 0)), end=(__import__("datetime").time(21, 0))),
        duration_minutes=60,
    )

    decision = handle_meeting_request(request, date(2026, 9, 18), config, "routine.json")

    assert decision.action == "reschedule_and_confirm"
    assert decision.confirmed_slot is not None
    assert decision.rescheduled_commitment is not None
    assert "Gym" in decision.rescheduled_commitment.title


def test_unknown_requester_gets_alternatives():
    config = Config("config.yaml")
    request = MeetingRequest(
        requester_id="unknown-person",
        requester_name="Unknown Person",
        channel="slack",
        message_text="Can we meet at 8:00 PM today?",
        requested_date=date(2026, 9, 18),
        requested_time_slot=TimeSlot(start=(__import__("datetime").time(20, 0)), end=(__import__("datetime").time(21, 0))),
        duration_minutes=60,
    )

    decision = handle_meeting_request(request, date(2026, 9, 18), config, "routine.json")

    assert decision.action == "decline"
    assert len(decision.alternative_slots) > 0
    assert "free" in decision.reply_message.lower()


def test_chatbot_explains_free_slots():
    bot = RoutineChatbot()
    response = bot.respond("When am I free today?")

    assert "free" in response.lower()
    assert "today" in response.lower()
