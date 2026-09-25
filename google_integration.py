from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from env_loader import load_project_env
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_project_env()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",   # Sheets read/write
    "https://www.googleapis.com/auth/drive.file",     # find/create files in Drive
]
# NOTE: if you already have token.json from before Sheets was added,
# delete it and re-run `python google_integration.py` to re-authenticate.


class GoogleIntegration:
    """Real Google API wrapper with credential bootstrap logic."""

    def __init__(self, credentials_path: str | None = None, token_path: str | None = None):
        self.credentials_path = credentials_path or os.getenv("GOOGLE_CALENDAR_CREDENTIALS_PATH", "credentials.json")
        self.token_path = token_path or os.getenv("GOOGLE_CALENDAR_TOKEN_PATH", "token.json")
        self.creds = self._load_credentials()

    def _load_credentials(self):
        creds = None
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            elif os.path.exists(self.credentials_path):
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
                Path(self.token_path).parent.mkdir(parents=True, exist_ok=True)
                with open(self.token_path, "w", encoding="utf-8") as token:
                    token.write(creds.to_json())
            else:
                return None
        return creds

    def get_calendar_service(self):
        if self.creds is None:
            raise RuntimeError("Google Calendar credentials are not configured. Add credentials.json or set up a token first.")
        return build("calendar", "v3", credentials=self.creds)

    def get_gmail_service(self):
        if self.creds is None:
            raise RuntimeError("Gmail credentials are not configured. Add credentials.json or set up a token first.")
        return build("gmail", "v1", credentials=self.creds)

    def get_sheets_service(self):
        if self.creds is None:
            raise RuntimeError("Google credentials not configured. Run: python google_integration.py")
        return build("sheets", "v4", credentials=self.creds)

    def get_drive_service(self):
        if self.creds is None:
            raise RuntimeError("Google credentials not configured. Run: python google_integration.py")
        return build("drive", "v3", credentials=self.creds)

    def get_sheets_integration(self):
        """Return a ready SheetsIntegration instance (needs Sheets + Drive scopes)."""
        from sheets_integration import SheetsIntegration
        return SheetsIntegration(self.creds)

    def list_upcoming_events(self, max_results: int = 10) -> List[Dict[str, Any]]:
        service = self.get_calendar_service()
        events_result = service.events().list(
            calendarId="primary",
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return events_result.get("items", [])

    def create_event(self, summary: str, start_iso: str, end_iso: str, attendees: Optional[List[str]] = None) -> Dict[str, Any]:
        service = self.get_calendar_service()
        event = {
            "summary": summary,
            "start": {"dateTime": start_iso, "timeZone": "UTC"},
            "end": {"dateTime": end_iso, "timeZone": "UTC"},
            "attendees": [{"email": email} for email in (attendees or [])],
        }
        return service.events().insert(calendarId="primary", body=event).execute()

    def list_recent_messages(self, max_results: int = 10) -> List[Dict[str, Any]]:
        service = self.get_gmail_service()
        result = service.users().messages().list(userId="me", maxResults=max_results).execute()
        return result.get("messages", [])

    def send_email(self, to_email: str, subject: str, body: str) -> Dict[str, Any]:
        service = self.get_gmail_service()
        from email.mime.text import MIMEText
        import base64

        msg = MIMEText(body)
        msg["to"] = to_email
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return service.users().messages().send(userId="me", body={"raw": raw}).execute()


def main() -> None:
    integration = GoogleIntegration()
    if integration.creds is None:
        print("Google credentials are not configured yet. Add client_secret JSON file and run the OAuth flow.")
        return
    print("Google OAuth credentials loaded successfully.")
    print("Upcoming events:")
    try:
        events = integration.list_upcoming_events(max_results=3)
        print(events)
    except Exception as exc:
        print(f"Google API access error: {exc}")


if __name__ == "__main__":
    main()
