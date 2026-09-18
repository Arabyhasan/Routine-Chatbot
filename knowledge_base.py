from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from models import Commitment, DayOfWeek


DEFAULT_RUNTIME_POLICY = {
    "general_chat": "gemini",
    "structured_intent": "gemini",
    "email_drafting": "gemini",
    "fallback": "project_logic",
}


class UserKnowledgeBase:
    """Persistent memory layer with structured categories for preferences, constraints, and personal details."""

    def __init__(self, path: str = "knowledge_store.json"):
        self.path = Path(path)
        self._memory = self._load()

    def _classify_with_llm(self, text: str) -> Optional[Dict[str, str]]:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None

        model_name = self._resolve_gemini_model()
        if not model_name:
            return None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        prompt = (
            "Classify the user's statement into exactly one category: preferences, constraints, personal, goals, or routines. "
            "Return valid JSON with keys 'category' and 'fact'. "
            "If the statement is not a personal fact, return {'category': 'preferences', 'fact': '<short fact>'}.\n\n"
            f"Statement: {text}"
        )
        try:
            response = __import__("requests").post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            if response.status_code != 200:
                return None
            data = response.json()
            for candidate in data.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if isinstance(part, dict) and "text" in part:
                        payload = part["text"].strip()
                        try:
                            parsed = json.loads(payload)
                            if isinstance(parsed, dict) and parsed.get("category") and parsed.get("fact"):
                                return {"category": str(parsed["category"]).lower(), "fact": str(parsed["fact"]).strip()}
                        except Exception:
                            continue
        except Exception:
            return None
        return None

    def _resolve_gemini_model(self) -> Optional[str]:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None

        candidates = [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
        ]

        for model in candidates:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                probe = __import__("requests").post(
                    url,
                    json={"contents": [{"parts": [{"text": "Return exactly: MODEL_OK"}]}]},
                    timeout=20,
                )
                if probe.status_code == 200:
                    return model
            except Exception:
                continue
        return candidates[0]

    def _load(self) -> Dict[str, List[Dict[str, str]]]:
        if not self.path.exists():
            return self._empty_memory()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                return self._empty_memory()
            memory = self._empty_memory()
            for category, items in data.items():
                if category not in memory:
                    continue
                for item in items or []:
                    if isinstance(item, dict) and item.get("fact"):
                        memory[category].append({
                            "fact": str(item["fact"]),
                            "source": str(item.get("source", "user")),
                        })
            return memory
        except (json.JSONDecodeError, OSError):
            return self._empty_memory()

    @staticmethod
    def _empty_memory() -> Dict[str, List[Dict[str, str]]]:
        return {
            "preferences": [],
            "constraints": [],
            "personal": [],
            "goals": [],
            "routines": [],
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self._memory, handle, indent=2)

    def add_fact(self, fact: str, category: str = "preferences", source: str = "user") -> Dict[str, str]:
        normalized = (fact or "").strip()
        if not normalized:
            return {"fact": "", "source": source}
        if category not in self._memory:
            self._memory[category] = []
        existing = self._memory[category]
        if any(item.get("fact", "").lower() == normalized.lower() for item in existing):
            return {"fact": normalized, "source": source}
        item = {"fact": normalized, "source": source}
        existing.append(item)
        self._save()
        return item

    def get_facts(self) -> List[Dict[str, str]]:
        flattened = []
        for category in self._memory.values():
            for item in category:
                flattened.append(dict(item))
        return flattened

    def get_memory_by_category(self) -> Dict[str, List[Dict[str, str]]]:
        return {category: [dict(item) for item in items] for category, items in self._memory.items()}

    def build_profile_summary(self) -> str:
        """Generate a compact user profile summary from saved memory, using the model when possible."""
        facts = self.get_facts()
        if not facts:
            return "No remembered user facts yet."

        summary_text = "\n".join(f"- {item['fact']}" for item in facts[:20])
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return summary_text

        model_name = self._resolve_gemini_model()
        if not model_name:
            return summary_text

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        prompt = (
            "Condense the following notes into a brief, natural, long-term user profile summary. "
            "Keep it compact, useful, and human-readable.\n\n"
            f"Notes:\n{summary_text}"
        )
        try:
            response = __import__("requests").post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=30)
            if response.status_code != 200:
                return summary_text
            data = response.json()
            for candidate in data.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if isinstance(part, dict) and "text" in part:
                        text = str(part["text"]).strip()
                        if text:
                            return text
        except Exception:
            pass
        return summary_text

    def remember_from_text(self, text: str) -> List[Dict[str, str]]:
        raw = (text or "").strip()
        if not raw:
            return []

        llm_result = self._classify_with_llm(raw)
        if llm_result:
            category = llm_result["category"] if llm_result["category"] in self._memory else "preferences"
            fact = llm_result["fact"]
            return [self.add_fact(fact, category=category, source="user")]

        category_rules = {
            "preferences": [
                r"i\s+(?:prefer|like|love|want|need)\s+(.+)",
                r"i\s+don'?t\s+like\s+(.+)",
                r"remember\s+(?:that\s+)?i\s+(?:prefer|like|love|want|need)\s+(.+)",
            ],
            "constraints": [
                r"i\s+can(?:'?t| not)\s+(.+)",
                r"i\s+must\s+(.+)",
                r"only\s+(?:on|during)\s+(.+)",
            ],
            "personal": [
                r"my\s+(?:name|email|phone|timezone|location|language)\s+(?:is|are)\s+(.+)",
                r"i\s+am\s+(.+)",
            ],
            "goals": [
                r"my\s+(?:goal|objective|aim)\s+(?:is|are)\s+(.+)",
                r"i\s+want\s+to\s+(.+)",
            ],
            "routines": [
                r"i\s+have\s+(.+?)\s+(?:every|each)\s+(.+)",
                r"i\s+have\s+(.+?)\s+at\s+(.+)",
                r"i\s+usually\s+(.+)",
            ],
        }

        saved = []
        for category, patterns in category_rules.items():
            for pattern in patterns:
                for match in re.finditer(pattern, raw, flags=re.IGNORECASE):
                    fact = match.group(1).strip().rstrip(".")
                    if len(fact) < 3:
                        continue
                    saved.append(self.add_fact(fact, category=category, source="user"))
        return saved


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
