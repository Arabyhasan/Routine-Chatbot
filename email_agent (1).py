from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

try:
    import anthropic
except Exception:  # pragma: no cover - optional dependency
    anthropic = None

# Current Claude API model id. Update here if Anthropic ships a newer default.
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"


def validate_email_address(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
    return bool(re.fullmatch(pattern, email.strip()))


class EmailAgent:
    """AI email drafting agent for any valid email address."""

    def __init__(self, model_name: str = DEFAULT_CLAUDE_MODEL):
        self.model_name = model_name
        self.last_error: str | None = None

    def _get_client(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            self.last_error = "ANTHROPIC_API_KEY is not set."
            return None
        if anthropic is None:
            self.last_error = "The 'anthropic' package is not installed."
            return None
        return anthropic.Anthropic(api_key=api_key)

    def _extract_text(self, response) -> str | None:
        if not hasattr(response, "content"):
            return str(response)
        parts = []
        for item in response.content:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
        if parts:
            return "\n\n".join(parts)
        return str(response.content)

    def _call_claude(self, to_email: str, subject: str, context: str) -> str | None:
        client = self._get_client()
        if client is None:
            return None

        prompt = (
            f"Write a concise but polished email.\n"
            f"Recipient: {to_email}\n"
            f"Subject: {subject}\n"
            f"Context: {context}\n"
            "Output a complete email draft with To, Subject, greeting, body, and sign-off."
        )

        try:
            response = client.messages.create(
                model=self.model_name,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            self.last_error = None
            return self._extract_text(response)
        except Exception as exc:  # pragma: no cover - network/SDK errors
            self.last_error = str(exc)
            return None

    def extract_email_intent(self, user_message: str) -> Dict[str, Any] | None:
        """Ask Claude to turn a free-text request into a structured send-email intent.

        Returns {"to_email": str, "subject": str, "body": str} or None if the
        model is unavailable / the response can't be parsed as valid JSON.
        """
        client = self._get_client()
        if client is None:
            return None

        prompt = (
            "A user sent this message to a scheduling assistant. If it is a request "
            "to send an email, extract the recipient, a short subject line, and a "
            "complete, polished email body written in the assistant's voice.\n\n"
            f"User message: {user_message!r}\n\n"
            "Respond with ONLY a JSON object, no other text, no markdown fences, "
            'in exactly this shape: {"to_email": "...", "subject": "...", "body": "..."}. '
            "If no email address is present, set to_email to an empty string."
        )

        try:
            response = client.messages.create(
                model=self.model_name,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            self.last_error = None
            text = self._extract_text(response) or ""
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
                cleaned = re.sub(r"```$", "", cleaned).strip()
            data = json.loads(cleaned)
            if not isinstance(data, dict) or "to_email" not in data:
                return None
            return {
                "to_email": (data.get("to_email") or "").strip(),
                "subject": (data.get("subject") or "").strip() or "Message from your assistant",
                "body": (data.get("body") or "").strip(),
            }
        except Exception as exc:  # pragma: no cover - network/SDK/JSON errors
            self.last_error = str(exc)
            return None

    def draft_email(self, to_email: str, subject: str, context: str) -> str:
        if not validate_email_address(to_email):
            raise ValueError(f"Invalid email address: {to_email}")

        claude_draft = self._call_claude(to_email, subject, context)
        if claude_draft:
            return claude_draft

        safe_subject = (subject or "Meeting request").strip() or "Meeting request"
        safe_context = (context or "").strip() or "Please let me know your availability."

        return (
            f"To: {to_email}\n"
            f"Subject: {safe_subject}\n\n"
            f"Hi,\n\n"
            f"{safe_context}\n\n"
            f"Please let me know a time that works for you.\n\n"
            f"Best,\n"
            f"Your assistant"
        )

    def compose_reply_for_free_slots(self, to_email: str, free_slots: List[str]) -> str:
        if not validate_email_address(to_email):
            raise ValueError(f"Invalid email address: {to_email}")
        if not free_slots:
            return self.draft_email(to_email, "Availability", "I don't have any openings right now.")

        slot_text = "; ".join(free_slots)
        return self.draft_email(
            to_email,
            "Availability",
            f"I am available at the following times: {slot_text}. Please let me know which works for you.",
        )

    def handle_user_request(self, user_message: str) -> Dict[str, Any]:
        text = (user_message or "").strip()
        if not text:
            return {"status": "needs_more_info", "message": "Please provide the email address and request."}

        match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        if not match:
            return {"status": "invalid_email", "message": "I could not find a valid email address in that request."}

        email = match.group(0)
        subject = "Meeting request"
        lowered = text.lower()
        if "when are you free" in lowered or "when are you available" in lowered:
            subject = "When are you free?"
        if any(word in lowered for word in ["cancel", "reschedule", "postpone"]):
            subject = "Rescheduling request"

        return {
            "status": "draft_ready",
            "to_email": email,
            "subject": subject,
            "draft": self.draft_email(email, subject, text),
            "model": self.model_name,
        }


class ClaudeAgent(EmailAgent):
    def __init__(self):
        super().__init__(model_name=DEFAULT_CLAUDE_MODEL)


class IntentAgent:
    """Route a user request to the right agent based on intent."""

    def __init__(self):
        self.email_agent = ClaudeAgent()

    def parse(self, user_message: str) -> Dict[str, Any]:
        text = (user_message or "").strip()
        lowered = text.lower()

        if any(token in lowered for token in ["email", "send email", "draft email", "ask ", "when are you free", "reschedule", "postpone", "cancel"]):
            email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
            if email_match:
                email = email_match.group(0)
                return {
                    "intent": "email",
                    "to_email": email,
                    "valid_email": validate_email_address(email),
                    "model": "claude",
                }
            return {"intent": "email", "to_email": None, "valid_email": False, "model": "claude"}

        if any(token in lowered for token in ["free today", "schedule", "meeting", "routine"]):
            return {"intent": "routine", "model": "routine"}

        return {"intent": "general", "model": "routine"}
