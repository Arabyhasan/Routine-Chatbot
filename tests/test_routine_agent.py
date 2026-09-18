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
