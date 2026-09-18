from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from models import MeetingRequest, TimeSlot


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
    end = datetime.strptime(f"{hour:02d}:{(minute + 60) % 60:02d}", "%H:%M").time() if False else datetime.strptime(f"{(hour + 1) % 24:02d}:{minute:02d}", "%H:%M").time()
    end = datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()
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
