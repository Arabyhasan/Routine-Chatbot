from __future__ import annotations

import json
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from chatbot import RoutineChatbot
from config_loader import Config
from google_integration import GoogleIntegration
from message_parser import parse_meeting_request_text
from priority import handle_meeting_request
from priority_manager import PriorityManager
from service_config import ServiceConfig
from slack_integration import SlackIntegration


class ProcessedMessageStore:
    """Dedupe incoming Slack/Gmail messages to avoid processing the same message twice."""

    def __init__(self, path: str = "processed_messages.json"):
        self.path = Path(path)
        self._cache = self._load()

    def _load(self) -> set[str]:
        if not self.path.exists():
            return set()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("processed", []))
        except (json.JSONDecodeError, OSError):
            return set()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"processed": sorted(self._cache)}, f)

    def should_process(self, message_id: str) -> bool:
        if not message_id:
            return False
        if message_id in self._cache:
            return False
        self._cache.add(message_id)
        self._save()
        return True


class AutomationWorker:
    """Main background worker for real Slack/Gmail event handling."""

    def __init__(self, config_path: str = "config.yaml", routine_path: str = "routine.json", service_config: ServiceConfig | None = None):
        self.config = Config(config_path)
        self.routine_path = routine_path
        self.service_config = service_config or ServiceConfig.from_env()
        self.processed_store = ProcessedMessageStore()
        self.slack = SlackIntegration() if self.service_config.slack_enabled else None
        self.google = GoogleIntegration() if self.service_config.gmail_enabled or self.service_config.calendar_enabled else None
        self.priority_manager = PriorityManager(self.config)
        self.bot = RoutineChatbot(config_path=config_path, routine_path=routine_path, service_config=self.service_config)

    def _handle_slack_message(self, raw_text: str, sender_id: str, sender_name: str, channel: str, message_id: str = "") -> Dict[str, Any]:
        key = message_id or f"{channel}:{sender_id}:{raw_text}"
        if not self.processed_store.should_process(key):
            return {"status": "duplicate", "message": "Message already processed."}

        reply = self.bot.respond(raw_text)
        if self.slack is not None and hasattr(self.slack, "send_message"):
            self.slack.send_message(channel, reply)
        return {"status": "processed", "reply": reply}

    def process_message(self, raw_text: str, sender_id: str, sender_name: str, channel: str, message_id: str = "") -> Dict[str, Any]:
        key = message_id or f"{channel}:{sender_id}:{raw_text}"
        if not self.processed_store.should_process(key):
            return {"status": "duplicate", "message": "Message already processed."}

        request = parse_meeting_request_text(raw_text, sender_id, sender_name, channel, message_id)
        if request.requested_time_slot is None:
            return {
                "status": "needs_clarification",
                "reply": f"Hi {sender_name}, please include a specific time like '7:30 PM' or '8pm'.",
            }

        priority_request = self.priority_manager.choose_priority_request([request]) if request else request
        decision = handle_meeting_request(request, date.today(), self.config, self.routine_path)
        if priority_request and priority_request.requester_id != request.requester_id:
            decision.reasoning = f"Priority order applied: {priority_request.requester_id} outranked the incoming request. " + decision.reasoning
        return {
            "status": decision.action,
            "reply": decision.reply_message,
            "reasoning": decision.reasoning,
        }

    def listen_for_slack_messages(self, poll_interval: int = 10, channel_filter: List[str] | None = None) -> None:
        if not self.service_config.slack_enabled or self.slack is None:
            print("Slack service disabled for this run; skipping Slack listener.")
            return
        if not self.slack.bot_token:
            raise RuntimeError("SLACK_BOT_TOKEN is missing in .env")

        print("Slack automation loop started. Polling for new direct messages and channel activity...")
        while True:
            try:
                channels = self.slack.list_channels()
                for channel in channels:
                    channel_id = channel.get("id")
                    if not channel_id:
                        continue
                    if channel_filter and channel_id not in channel_filter:
                        continue
                    messages = self.slack.fetch_unread_messages(channel_id)
                    for message in messages:
                        if message.get("subtype") in {"bot_message", "message_changed"}:
                            continue
                        text = message.get("text", "")
                        user = message.get("user")
                        if not text or not user:
                            continue
                        ts = message.get("ts", "")
                        key = f"slack:{channel_id}:{ts}"
                        if not self.processed_store.should_process(key):
                            continue
                        result = self._handle_slack_message(text, user, user, channel_id, key)
                        if result.get("reply"):
                            self.slack.send_message(channel_id, result["reply"])
            except Exception as exc:
                print(f"Slack poll error: {exc}")
            time.sleep(poll_interval)

    def poll_gmail_messages(self, poll_interval: int = 30) -> None:
        if not self.service_config.gmail_enabled or self.google is None:
            print("Gmail service disabled for this run; skipping Gmail listener.")
            return
        print("Gmail automation loop started. Polling for new messages...")
        while True:
            try:
                if self.google.creds is None:
                    print("Gmail not configured yet; waiting for credentials.")
                    time.sleep(poll_interval)
                    continue

                messages = self.google.list_recent_messages(max_results=10)
                for msg in messages:
                    msg_id = msg.get("id")
                    if not msg_id:
                        continue
                    if not self.processed_store.should_process(f"gmail:{msg_id}"):
                        continue
                    print(f"Gmail message detected: {msg_id}")
            except Exception as exc:
                print(f"Gmail poll error: {exc}")
            time.sleep(poll_interval)

    def start_service_workers(self, slack_interval: int = 10, gmail_interval: int = 30) -> List[threading.Thread]:
        threads: List[threading.Thread] = []
        if self.service_config.slack_enabled and self.slack is not None:
            thread = threading.Thread(target=self.listen_for_slack_messages, args=(slack_interval,), daemon=True)
            thread.start()
            threads.append(thread)
        if self.service_config.gmail_enabled and self.google is not None:
            thread = threading.Thread(target=self.poll_gmail_messages, args=(gmail_interval,), daemon=True)
            thread.start()
            threads.append(thread)
        return threads
