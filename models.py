"""
models.py — All data classes used across the Routine Agent.

Keep this file as the single source of truth for types.
If you add a field here, it propagates everywhere naturally.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, time, date
from typing import Optional, List
from enum import Enum


class DayOfWeek(str, Enum):
    MONDAY    = "monday"
    TUESDAY   = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY  = "thursday"
    FRIDAY    = "friday"
    SATURDAY  = "saturday"
    SUNDAY    = "sunday"


@dataclass
class TimeSlot:
    start: time
    end: time

    def overlaps(self, other: TimeSlot) -> bool:
        """True if this slot overlaps with another, boundary-exclusive."""
        return self.start < other.end and other.start < self.end

    def duration_minutes(self) -> int:
        start_m = self.start.hour * 60 + self.start.minute
        end_m   = self.end.hour   * 60 + self.end.minute
        return end_m - start_m

    def pretty(self) -> str:
        return f"{self.start.strftime('%I:%M %p')}–{self.end.strftime('%I:%M %p')}"


@dataclass
class Commitment:
    """A single recurring entry in your routine."""
    id:              str
    title:           str
    commitment_type: str        # must match a key in config.yaml → commitments
    days:            List[DayOfWeek]
    time_slot:       TimeSlot
    priority:        int        # 1–10; loaded from config, can be instance-overridden
    reschedulable:   bool
    notes:           str = ""
    calendar_event_id: Optional[str] = None   # filled in after Calendar API call


@dataclass
class RequesterProfile:
    """A person who can send meeting requests."""
    requester_id:  str    # Slack user ID or email
    display_name:  str
    priority:      int    # 1–10; from config.yaml → requesters
    relationship:  str    # "manager", "colleague", "unknown", etc.


@dataclass
class MeetingRequest:
    """A parsed meeting request extracted from Slack or Gmail."""
    requester_id:        str
    requester_name:      str
    channel:             str           # "slack" or "gmail"
    message_text:        str
    requested_date:      Optional[date]
    requested_time_slot: Optional[TimeSlot]
    duration_minutes:    int = 60
    raw_message_id:      str = ""      # Slack ts or Gmail message ID (for threading replies)
    reply_to_email:      str = ""      # Filled in for Gmail replies


@dataclass
class SchedulingDecision:
    """The outcome of running a MeetingRequest through the priority engine."""
    action:                 str              # "confirm" | "decline" | "reschedule_and_confirm"
    confirmed_slot:         Optional[TimeSlot]
    rescheduled_commitment: Optional[Commitment]
    alternative_slots:      List[TimeSlot]
    reply_message:          str              # ready to send as-is
    reasoning:              str              # for logging / supervisor demo
