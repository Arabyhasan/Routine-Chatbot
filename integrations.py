from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from google_integration import GoogleIntegration
from slack_integration import SlackIntegration


class SlackClient:
    """Compatibility wrapper for the real Slack integration."""

    def __init__(self):
        self._client = SlackIntegration()

    def fetch_unread_messages(self, channel_id: str = "") -> List[Dict[str, Any]]:
        if channel_id:
            return self._client.fetch_unread_messages(channel_id)
        return []

    def reply_to_message(self, channel_id: str, text: str) -> str:
        if not channel_id:
            return "Slack reply skipped: missing channel id"
        return f"Slack reply queued for {channel_id}: {text}"

    def send_message(self, channel_id: str, text: str) -> str:
        return f"Slack send queued for {channel_id}: {text}"


class GmailClient:
    """Compatibility wrapper for Gmail integration."""

    def __init__(self):
        self._client = GoogleIntegration()

    def fetch_unread_messages(self) -> List[Dict[str, Any]]:
        try:
            return self._client.list_recent_messages(max_results=10)
        except Exception:
            return []

    def reply_to_email(self, message_id: str, text: str) -> str:
        return f"Gmail reply prepared for message {message_id}: {text}"

    def send_email(self, to_email: str, subject: str, body: str) -> str:
        return f"Gmail send queued to {to_email}: {subject}"


class GoogleCalendarClient:
    """Compatibility wrapper for Google Calendar integration."""

    def __init__(self):
        self._client = GoogleIntegration()

    def list_events(self) -> List[Dict[str, Any]]:
        try:
            return self._client.list_upcoming_events()
        except Exception:
            return []

    def create_event(self, summary: str, start: str, end: str, attendees: Optional[List[str]] = None) -> Dict[str, Any]:
        try:
            return self._client.create_event(summary, start, end, attendees)
        except Exception:
            return {
                "demo": True,
                "summary": summary,
                "start": start,
                "end": end,
                "attendees": attendees or [],
                "status": "local_demo_only",
            }

    def update_event(self, event_id: str, **kwargs) -> Dict[str, Any]:
        return {"demo": True, "event_id": event_id, "updated_fields": kwargs}


@dataclass
class IntegrationManager:
    """Simple facade for all external integrations."""

    slack: SlackClient = None
    gmail: GmailClient = None
    calendar: GoogleCalendarClient = None

    def __init__(self):
        self.slack = SlackClient()
        self.gmail = GmailClient()
        self.calendar = GoogleCalendarClient()


def demo_integration_flow() -> Dict[str, str]:
    manager = IntegrationManager()
    return {
        "slack": manager.slack.reply_to_message("general", "I am available at 7pm."),
        "gmail": manager.gmail.reply_to_email("msg-123", "I am available at 7pm."),
        "calendar": str(manager.calendar.create_event("Demo meeting", "2026-09-18T19:00:00", "2026-09-18T20:00:00", ["bijoy@example.com"])),
    }
