from __future__ import annotations

import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()


class SlackIntegration:
    """Real Slack API wrapper for reads/replies. Requires env configuration."""

    def __init__(self):
        self.bot_token = os.getenv("SLACK_BOT_TOKEN")
        self.app_token = os.getenv("SLACK_APP_TOKEN")
        self.signing_secret = os.getenv("SLACK_SIGNING_SECRET")
        self.client = WebClient(token=self.bot_token) if self.bot_token else None

    def verify_connection(self) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("SLACK_BOT_TOKEN is missing. Add it to .env before running the bot.")

        try:
            return self.client.auth_test()
        except SlackApiError as exc:
            raise RuntimeError(f"Slack auth failed: {exc}") from exc

    def list_channels(self) -> List[Dict[str, Any]]:
        if not self.client:
            return [{"error": "SLACK_BOT_TOKEN is missing"}]
        try:
            response = self.client.conversations_list()
            return response.get("channels", [])
        except SlackApiError as exc:
            return [{"error": str(exc)}]

    def fetch_unread_messages(self, channel_id: str) -> List[Dict[str, Any]]:
        if not self.client:
            return [{"error": "SLACK_BOT_TOKEN is missing"}]
        try:
            response = self.client.conversations_history(channel=channel_id)
            return response.get("messages", [])
        except SlackApiError as exc:
            return [{"error": str(exc)}]

    def send_message(self, channel_id: str, text: str) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("SLACK_BOT_TOKEN is missing. Add it to .env before running the bot.")
        return self.client.chat_postMessage(channel=channel_id, text=text)

    def reply_to_message(self, channel_id: str, ts: str, text: str) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("SLACK_BOT_TOKEN is missing. Add it to .env before running the bot.")
        return self.client.chat_postMessage(channel=channel_id, text=text, thread_ts=ts)


def main() -> None:
    """Startup check for the real Slack bot. Helps you confirm env setup before listener mode."""
    integration = SlackIntegration()

    if not integration.bot_token:
        print("Slack startup failed: SLACK_BOT_TOKEN is not set in .env")
        return

    if not integration.app_token or not integration.signing_secret:
        print("Slack bot token is present, but Socket Mode is not configured yet.")
        print("Needed in .env: SLACK_APP_TOKEN and SLACK_SIGNING_SECRET")
        try:
            result = integration.verify_connection()
            print("Bot auth test passed:", result)
        except Exception as exc:
            print(f"Bot auth test failed: {exc}")
        return

    try:
        result = integration.verify_connection()
        print("Slack connection verified:", result)
        print("Listener is ready. Send a DM or mention to the bot.")
    except Exception as exc:
        print(f"Slack connection failed: {exc}")


if __name__ == "__main__":
    main()
