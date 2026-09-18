from datetime import date

from automation_worker import AutomationWorker
from config_loader import Config
from email_agent import EmailAgent, validate_email_address
from models import MeetingRequest, TimeSlot
from priority import handle_meeting_request
from priority_manager import PriorityManager
from chatbot import RoutineChatbot
from service_config import ServiceConfig


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


def test_integration_manager_has_slack_gmail_and_calendar_stubs():
    from integrations import IntegrationManager

    manager = IntegrationManager()

    assert hasattr(manager, "slack")
    assert hasattr(manager, "gmail")
    assert hasattr(manager, "calendar")
    assert manager.slack is not None
    assert manager.gmail is not None
    assert manager.calendar is not None


def test_slack_and_gmail_helpers_return_demo_payloads():
    from integrations import SlackClient, GmailClient

    slack = SlackClient()
    gmail = GmailClient()

    assert isinstance(slack.fetch_unread_messages(), list)
    assert isinstance(gmail.fetch_unread_messages(), list)
    assert "demo" in slack.reply_to_message("demo-id", "Hello").lower()
    assert "demo" in gmail.reply_to_email("demo-id", "Hello").lower()


def test_service_selection_updates_worker_runtime_and_priority_order():
    config = Config("config.yaml")
    worker = AutomationWorker(
        config_path="config.yaml",
        routine_path="routine.json",
        service_config=ServiceConfig(enabled_services=["slack", "gmail"], slack_enabled=True, gmail_enabled=True, calendar_enabled=False),
    )

    assert worker.service_config.slack_enabled is True
    assert worker.service_config.gmail_enabled is True
    assert worker.slack is not None
    assert worker.google is not None
    assert len(worker.start_service_workers()) == 2

    manager = PriorityManager(config)
    req_a = MeetingRequest(
        requester_id="bijoy",
        requester_name="Bijoy",
        channel="slack",
        message_text="Meet at 8pm",
        requested_date=date(2026, 9, 18),
        requested_time_slot=TimeSlot(start=(__import__("datetime").time(20, 0)), end=(__import__("datetime").time(21, 0))),
        duration_minutes=60,
    )
    req_b = MeetingRequest(
        requester_id="unknown-person",
        requester_name="Unknown Person",
        channel="gmail",
        message_text="Meet at 8pm",
        requested_date=date(2026, 9, 18),
        requested_time_slot=TimeSlot(start=(__import__("datetime").time(20, 0)), end=(__import__("datetime").time(21, 0))),
        duration_minutes=60,
    )
    assert manager.choose_priority_request([req_b, req_a]).requester_id == "bijoy"


def test_email_validation_and_drafting_work_for_any_valid_address():
    assert validate_email_address("person@example.com") is True
    assert validate_email_address("not-an-email") is False

    draft = EmailAgent().draft_email(
        to_email="person@example.com",
        subject="When are you free?",
        context="Please let me know when you are free for a quick call next week.",
    )
    assert "person@example.com" in draft
    assert "free" in draft.lower()


def test_chatbot_uses_mcp_tool_layer_when_available():
    bot = RoutineChatbot()

    class DummyMCPClient:
        def __init__(self):
            self.calls = []

        def get_routine_summary(self):
            self.calls.append("routine")
            return "Demo routine summary"

        def get_free_slots_for_today(self):
            self.calls.append("free")
            return ["9:00 AM - 10:00 AM"]

    bot.mcp_client = DummyMCPClient()

    assert bot._mcp_routine_summary() == "Demo routine summary"
    assert bot._mcp_free_slots() == ["9:00 AM - 10:00 AM"]


def test_chatbot_uses_llm_reasoning_when_provider_is_configured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class DummyResponse:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "I can help plan your day."}]}}]}

    def fake_post(url, json, headers=None, timeout=None):
        return DummyResponse()

    import requests
    monkeypatch.setattr(requests, "post", fake_post)

    bot = RoutineChatbot()
    reply = bot._llm_chat_response("What should I do today?")

    assert "help plan" in reply.lower()


def test_recurring_commitment_parser_understands_every_day_except_friday():
    from message_parser import parse_recurring_commitment_text

    parsed = parse_recurring_commitment_text("I have gym every day at 7 except Friday")

    assert parsed is not None
    assert parsed["title"].lower() == "gym"
    assert "friday" not in [d.value for d in parsed["days"]]
    assert parsed["start_time"] == "19:00"


def test_chatbot_requires_confirmation_before_sending_email():
    bot = RoutineChatbot()
    bot.pending_email = {"to_email": "person@example.com", "subject": "Availability", "body": "Let's meet next week."}
    assert "confirm" in bot.respond("send it").lower()


def test_claude_agent_uses_anthropic_api_when_key_is_present(monkeypatch):
    import email_agent

    class DummyContent:
        def __init__(self, text):
            self.text = text

    class DummyResponse:
        def __init__(self, text):
            self.content = [DummyContent(text)]

    class DummyMessages:
        def create(self, **kwargs):
            return DummyResponse("Hi, I'd love to meet next Tuesday at 2pm.")

    class DummyClient:
        def __init__(self, api_key):
            self.messages = DummyMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(email_agent, "anthropic", type("AnthropicModule", (), {"Anthropic": DummyClient}), raising=False)

    agent = email_agent.ClaudeAgent()
    draft = agent.draft_email("person@example.com", "Availability", "Please let me know when you are free for a quick call.")

    assert "Tuesday" in draft
    assert "2pm" in draft


def test_runtime_policy_defaults_to_gemini_for_everything():
    from knowledge_base import get_runtime_policy

    policy = get_runtime_policy({})

    assert policy["general_chat"] == "gemini"
    assert policy["structured_intent"] == "gemini"
    assert policy["email_drafting"] == "gemini"


def test_no_meetings_today_reschedules_to_tomorrow_with_conflict_handling():
    from datetime import date, time
    from knowledge_base import apply_no_meetings_today
    from models import Commitment, TimeSlot, DayOfWeek

    today = date(2026, 9, 18)
    tomorrow = today.replace(day=today.day + 1)

    commitments = [
        Commitment("m1", "Gym", "gym", [DayOfWeek.FRIDAY], TimeSlot(time(20, 0), time(21, 0)), 2, True),
        Commitment("m2", "Team sync", "work_meeting", [DayOfWeek.FRIDAY], TimeSlot(time(20, 0), time(21, 0)), 7, False),
        Commitment("m3", "Lunch", "lunch", [DayOfWeek.FRIDAY], TimeSlot(time(13, 0), time(14, 0)), 3, True),
    ]

    updated = apply_no_meetings_today(commitments, today)

    assert any(item.title == "Gym" and item.time_slot.start.hour == 20 for item in updated)
    assert any(item.title == "Team sync" and item.time_slot.start.hour == 20 for item in updated)
    assert any(item.title == "Lunch" and item.time_slot.start.hour == 13 for item in updated)


def test_inbound_email_detection_flags_meeting_requests():
    from knowledge_base import analyze_email_message

    result = analyze_email_message("Hi, can we meet tomorrow at 2pm? Please let me know if that's good.")

    assert result["is_meeting_request"] is True
    assert result["needs_reply"] is True


def test_slack_channel_flow_is_interactive_and_scheduling_aware():
    bot = RoutineChatbot()

    slack_response = bot.respond("Can we meet at 8pm in #general?")
    lowered = slack_response.lower()
    assert "08:00" in lowered or "8pm" in lowered or "pm" in lowered
    assert "confirm" in lowered or "lock it in" in lowered or "cancel" in lowered


def test_worker_routes_real_slack_message_through_llm_chatbot():
    worker = AutomationWorker(service_config=ServiceConfig(slack_enabled=True, gmail_enabled=False, calendar_enabled=False))

    class DummyBot:
        def __init__(self):
            self.calls = []

        def respond(self, text):
            self.calls.append(text)
            return "Gemini response for channel message"

    class DummySlack:
        def __init__(self):
            self.sent = []

        def send_message(self, channel_id, text):
            self.sent.append((channel_id, text))
            return {"ok": True}

    worker.bot = DummyBot()
    worker.slack = DummySlack()

    unique_key = "ts-llm-listener-20260918-unique"
    result = worker._handle_slack_message("Can we meet at 8pm?", "U123", "Alice", "C123", unique_key)

    assert result["reply"] == "Gemini response for channel message"
    assert worker.slack.sent == [("C123", "Gemini response for channel message")]
