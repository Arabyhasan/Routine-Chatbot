"""
email_agent.py — Email drafting via whichever LLM provider is configured.

BUG FIX: this used to hardcode `os.getenv("ANTHROPIC_API_KEY")` and call the
Anthropic SDK directly. Anyone running on the app's own recommended free tier
(GROQ_API_KEY or GEMINI_API_KEY, no Anthropic key) got silently downgraded to
the generic template below with no real draft and no error — a real
functional gap. Now routes through the same llm_provider.LLMProvider used by
the rest of the app, so Claude/Groq/Gemini all work identically here.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from llm_provider import LLMProvider


def validate_email_address(email: str) -> bool:
    if not email or not isinstance(email, str):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email.strip()))


class EmailAgent:
    """Draft emails using whichever LLM is configured. Falls back to a template if none is available."""

    def __init__(self, model_name: str | None = None):
        # model_name kept for backward compatibility with callers that pass
        # it explicitly; LLMProvider picks its own model per-provider when
        # this is left as None, matching chatbot.py's behaviour.
        self.model_name = model_name
        self.provider = LLMProvider()

    def draft_email(self, to_email: str, subject: str, context: str) -> str:
        if not validate_email_address(to_email):
            raise ValueError(f"Invalid email: {to_email}")

        if self.provider.is_configured:
            try:
                prompt = (
                    f"Write a concise, professional email.\n"
                    f"To: {to_email}\nSubject: {subject}\nContext: {context}\n\n"
                    "Output only the email body (no To/Subject headers). "
                    "Start with a greeting, include the main message, end with a sign-off."
                )
                result = self.provider.create_message(
                    messages=[{"role": "user", "content": prompt}],
                    anthropic_tools=[],
                    system="You draft clear, professional emails on the user's behalf.",
                    max_tokens=400,
                )
                text = (result.get("text") or "").strip()
                # llm_provider.create_message() reports failures as a normal
                # "end_turn" result rather than raising — without this check,
                # a live API failure would be shown as if it were the actual
                # email draft. BUG FIX: this used to check text.startswith(...)
                # against one specific error-message shape, but llm_provider.py
                # actually has 5 different failure message formats (missing
                # package, not configured, two different API-error prefixes),
                # only one of which matched — the others leaked raw errors to
                # the user. is_error is an explicit flag set at every one of
                # those failure sites, so no guessing is needed.
                if text and not result.get("is_error"):
                    return text
            except Exception:
                pass

        # Template fallback — only reached if no provider is configured at
        # all, or the live call genuinely failed (not just "wrong provider").
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
            "model": self.model_name or self.provider.display_name,
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
