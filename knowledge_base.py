from __future__ import annotations

import os
import re
from copy import deepcopy
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional

from models import Commitment, DayOfWeek


DEFAULT_RUNTIME_POLICY = {
    "general_chat": "gemini",
    "structured_intent": "gemini",
    "email_drafting": "gemini",
    "fallback": "project_logic",
}


def get_runtime_policy(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return the single runtime policy used by the assistant.

    For now, all reasoning and drafting is routed through Gemini only.
    """
    effective_env = os.environ if env is None else env
    general_chat = str(effective_env.get("GENERAL_CHAT_PROVIDER") or effective_env.get("LLM_PROVIDER") or "gemini").lower()
    structured_intent = str(effective_env.get("STRUCTURED_INTENT_PROVIDER") or effective_env.get("LLM_PROVIDER") or "gemini").lower()
    email_drafting = str(effective_env.get("EMAIL_DRAFTING_PROVIDER") or effective_env.get("LLM_PROVIDER") or "gemini").lower()

    valid_models = {"gemini", "openai", "claude", "chatgpt", "anthropic", "google"}
    if general_chat not in valid_models:
        general_chat = "gemini"
    if structured_intent not in valid_models:
        structured_intent = "gemini"
    if email_drafting not in valid_models:
        email_drafting = "gemini"

    return {
        "general_chat": general_chat,
        "structured_intent": structured_intent,
        "email_drafting": email_drafting,
        "fallback": "project_logic",
    }


def analyze_email_message(message_text: str) -> Dict[str, Any]:
    """Determine whether an incoming email or message is a meeting request."""
    text = (message_text or "").strip()
    lowered = text.lower()

    meeting_terms = [
        "meet",
        "meeting",
        "call",
        "chat",
        "availability",
        "when are you free",
        "can we",
        "could we",
        "are you free",
    ]
    time_pattern = re.search(r"\b(?:today|tomorrow|next|at\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm))\b", lowered)

    is_meeting_request = bool(any(term in lowered for term in meeting_terms) and time_pattern)
    needs_reply = is_meeting_request or any(term in lowered for term in ["reply", "follow up", "available", "availability"])

    return {
        "raw_text": text,
        "is_meeting_request": is_meeting_request,
        "needs_reply": needs_reply,
        "why": "meeting request detected" if is_meeting_request else "not recognized as a meeting request",
    }


def _next_weekday_name(day: DayOfWeek) -> DayOfWeek:
    names = [
        DayOfWeek.MONDAY,
        DayOfWeek.TUESDAY,
        DayOfWeek.WEDNESDAY,
        DayOfWeek.THURSDAY,
        DayOfWeek.FRIDAY,
        DayOfWeek.SATURDAY,
        DayOfWeek.SUNDAY,
    ]
    current_index = names.index(day)
    return names[(current_index + 1) % len(names)]


def apply_no_meetings_today(commitments: Iterable[Commitment], today: date) -> List[Commitment]:
    """Cancel meetings for today and reschedule the conflicting ones to tomorrow.

    The rule is:
      - keep the first meeting today if it conflicts with another item
      - move the later conflicting slot to the following day at the same time
      - leave non-conflicting slots in place when the user explicitly cancels the day
    """
    today_name = DayOfWeek(today.strftime("%A").lower())
    tomorrow_name = _next_weekday_name(today_name)
    updated: List[Commitment] = []
    kept_today: List[Commitment] = []

    for commitment in sorted(commitments, key=lambda item: item.time_slot.start):
        if today_name not in commitment.days:
            updated.append(commitment)
            continue

        conflict = any(
            existing.time_slot.overlaps(commitment.time_slot)
            for existing in kept_today
        )

        if conflict:
            moved = deepcopy(commitment)
            moved.days = [tomorrow_name]
            moved.notes = f"Rescheduled from {today.strftime('%Y-%m-%d')} after 'no meetings today' command."
            updated.append(moved)
            continue

        kept_today.append(commitment)
        updated.append(commitment)

    for item in updated:
        if today_name in item.days and item not in kept_today:
            item.days = [tomorrow_name]
            item.notes = f"Moved to {tomorrow_name.value} after 'no meetings today'."

    return updated
