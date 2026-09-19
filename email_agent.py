"""
email_agent.py — Email drafting via Claude API.
Fixes: ClaudeAgent had model_name="claude" (invalid). Safe import. None-default model.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List

try:
    import anthropic
except Exception:
    anthropic = None


def validate_email_address(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email.strip()))


class EmailAgent:
    """Draft emails using Claude. Falls back to a template if Claude isn't available."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    def draft_email(self, to_email: str, subject: str, context: str) -> str:
        if not validate_email_address(to_email):
            raise ValueError(f"Invalid email: {to_email}")

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key and anthropic is not None:
            try:
                client = anthropic.Anthropic(api_key=api_key)
                prompt = (
                    f"Write a concise, professional email.\n"
                    f"To: {to_email}\nSubject: {subject}\nContext: {context}\n\n"
                    "Output only the email body (no To/Subject headers). "
                    "Start with a greeting, include the main message, end with a sign-off."
                )
                resp = client.messages.create(
                    model=self.model_name,
                    max_tokens=400,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = next(
                    (b.text for b in resp.content if getattr(b, "type", "") == "text"),
                    None,
                )
                if text:
                    return text.strip()
            except Exception:
                pass

        # Template fallback
        safe_context = (context or "").strip() or "Please let me know your availability."
        return (
            f"Hi,\n\n"
            f"{safe_context}\n\n"
            f"Please let me know if you have any questions.\n\n"
            f"Best regards"
        )

    def compose_reply_for_free_slots(self, to_email: str, free_slots: List[str]) -> str:
        slot_text = "; ".join(free_slots) if free_slots else "No openings right now."
        return self.draft_email(
            to_email, "Availability",
            f"I am available at: {slot_text}. Please let me know which works for you.",
        )

    def handle_user_request(self, user_message: str) -> Dict[str, Any]:
        text = (user_message or "").strip()
        match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        if not match:
            return {"status": "invalid_email", "message": "No valid email address found."}
        email = match.group(0)
        lowered = text.lower()
        subject = "Meeting request"
        if "cancel" in lowered or "reschedule" in lowered:
            subject = "Rescheduling request"
        elif "free" in lowered or "available" in lowered:
            subject = "Availability"
        return {
            "status": "draft_ready",
            "to_email": email,
            "subject": subject,
            "draft": self.draft_email(email, subject, text),
            "model": self.model_name,
        }


# Backward-compat aliases
class ClaudeAgent(EmailAgent):
    def __init__(self):
        super().__init__()  # uses env var / default — no longer hardcoded "claude"


class IntentAgent:
    def parse(self, user_message: str) -> Dict[str, Any]:
        text = (user_message or "").strip().lower()
        email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", user_message or "")
        if any(t in text for t in ["email", "send email", "draft email"]) and email_match:
            return {"intent": "email", "to_email": email_match.group(0), "valid_email": True}
        if email_match:
            return {"intent": "email", "to_email": email_match.group(0), "valid_email": True}
        if any(t in text for t in ["free today", "schedule", "meeting", "routine"]):
            return {"intent": "routine"}
        return {"intent": "general"}
