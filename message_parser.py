from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Optional

from models import DayOfWeek, MeetingRequest, TimeSlot


def _parse_time_value(value: str):
    value = value.strip().lower()
    hour = 0
    minute = 0

    if re.match(r"^\d{1,2}:\d{2}\s*(am|pm)?$", value):
        time_part, suffix = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm)?$", value, re.I).groups()
        hour = int(time_part)
        minute = int(suffix or "0") if False else int(re.match(r"^(\d{1,2}):(\d{2})", value).group(2))
        suffix = (suffix or "").lower()
        if suffix == "pm" and hour < 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute

    if re.match(r"^\d{1,2}\s*(am|pm)$", value):
        match = re.match(r"^(\d{1,2})\s*(am|pm)?$", value, re.I)
        hour = int(match.group(1))
        suffix = (match.group(2) or "").lower()
        if suffix == "pm" and hour < 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            return hour, 0

    return None


def _parse_clock_time(value: str):
    value = (value or "").strip().lower()
    if not value:
        return None

    match = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", value, re.I)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    suffix = (match.group(3) or "").lower()

    if suffix == "pm" and hour < 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0

    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def parse_recurring_commitment_text(text: str) -> Optional[Dict[str, Any]]:
    """Parse recurring schedule instructions like 'gym every day at 7 except friday'."""
    if not text:
        return None

    normalized = text.strip().lower()
    if "every" not in normalized and "each" not in normalized:
        return None

    title = "Commitment"
    if "gym" in normalized:
        title = "Gym"
    elif "run" in normalized or "jog" in normalized:
        title = "Run"
    elif "meeting" in normalized:
        title = "Meeting"

    candidate_time = None
    for phrase in re.findall(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", text, re.I):
        parsed = _parse_clock_time(phrase)
        if parsed:
            candidate_time = parsed
            break
    if candidate_time is None:
        return None

    hour, minute = candidate_time
    if re.search(r"\bat\s+\d{1,2}\b", text, re.I) and not re.search(r"\b(?:am|pm)\b", text, re.I) and hour < 12:
        hour += 12

    days = [
        DayOfWeek.MONDAY,
        DayOfWeek.TUESDAY,
        DayOfWeek.WEDNESDAY,
        DayOfWeek.THURSDAY,
        DayOfWeek.FRIDAY,
        DayOfWeek.SATURDAY,
        DayOfWeek.SUNDAY,
    ]

    excluded = []
    for day_name in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        if f"except {day_name}" in normalized or f"excluding {day_name}" in normalized or f"not {day_name}" in normalized:
            excluded.append(day_name)
        if f"every {day_name}" in normalized or f"each {day_name}" in normalized:
            excluded = []
            days = [DayOfWeek(day_name)]
            break

    if excluded:
        days = [d for d in days if d.value not in excluded]

    if not days:
        return None

    return {
        "title": title,
        "days": days,
        "start_time": f"{hour:02d}:{minute:02d}",
        "end_time": f"{(hour + 1) % 24:02d}:{minute:02d}",
    }


def parse_meeting_request_text(text: str, sender_id: str, sender_name: str, channel: str, raw_message_id: str = "") -> MeetingRequest:
    """Parse a simple meeting request into a MeetingRequest structure."""
    normalized = text.strip().lower()
    time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.I)
    if not time_match:
        return MeetingRequest(
            requester_id=sender_id,
            requester_name=sender_name,
            channel=channel,
            message_text=text,
            requested_date=None,
            requested_time_slot=None,
            duration_minutes=60,
            raw_message_id=raw_message_id,
        )

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    suffix = (time_match.group(3) or "").lower()
    if suffix == "pm" and hour < 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0

    start = datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()
    end = datetime.strptime(f"{(hour + 1) % 24:02d}:{minute:02d}", "%H:%M").time()
    requested_date = date.today()

    return MeetingRequest(
        requester_id=sender_id,
        requester_name=sender_name,
        channel=channel,
        message_text=text,
        requested_date=requested_date,
        requested_time_slot=TimeSlot(start=start, end=end),
        duration_minutes=60,
        raw_message_id=raw_message_id,
    )
