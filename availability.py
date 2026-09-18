"""
availability.py — Free slot detection and schedule summarization.

These functions are PURE — they take commitments as input and return answers.
No file I/O happens here; that's routine_manager.py's job.
This makes everything here trivially testable.
"""
from __future__ import annotations
from datetime import date, time, datetime, timedelta
from typing import List, Optional, Tuple

from models import TimeSlot, Commitment, DayOfWeek

# Boundaries for "available working hours"
WORK_START = time(8, 0)
WORK_END   = time(22, 0)

# Granularity when scanning for free slots (every 30 min)
SLOT_STEP_MINUTES = 30


def _weekday_name(d: date) -> DayOfWeek:
    return DayOfWeek(d.strftime("%A").lower())


def is_slot_free(
    target_date: date,
    requested_slot: TimeSlot,
    commitments: List[Commitment],
) -> Tuple[bool, Optional[Commitment]]:
    """
    Check whether a time slot is free on a given date.

    Returns:
        (True, None)            — slot is free
        (False, <Commitment>)   — slot conflicts with that commitment
    """
    day = _weekday_name(target_date)
    for c in commitments:
        if day in c.days and requested_slot.overlaps(c.time_slot):
            return False, c
    return True, None


def get_free_slots(
    target_date: date,
    commitments: List[Commitment],
    duration_minutes: int = 60,
) -> List[TimeSlot]:
    """
    Return every free slot of at least `duration_minutes` on `target_date`.
    Scans from WORK_START to WORK_END in SLOT_STEP_MINUTES increments.
    """
    day = _weekday_name(target_date)
    busy = [c.time_slot for c in commitments if day in c.days]

    free_slots: List[TimeSlot] = []
    cursor = datetime.combine(target_date, WORK_START)
    day_end = datetime.combine(target_date, WORK_END)
    step = timedelta(minutes=SLOT_STEP_MINUTES)
    span = timedelta(minutes=duration_minutes)

    while cursor + span <= day_end:
        candidate = TimeSlot(
            start=cursor.time(),
            end=(cursor + span).time(),
        )
        if not any(candidate.overlaps(b) for b in busy):
            free_slots.append(candidate)
        cursor += step

    return free_slots


def summarize_day(target_date: date, commitments: List[Commitment]) -> str:
    """Human-readable schedule summary — used by the conversational Q&A mode."""
    day = _weekday_name(target_date)
    day_commitments = sorted(
        [c for c in commitments if day in c.days],
        key=lambda c: c.time_slot.start,
    )

    label = target_date.strftime("%A, %B %d")
    if not day_commitments:
        return f"You have no commitments on {label}. Wide open day!"

    lines = [f"📅  Schedule for {label}:"]
    for c in day_commitments:
        lock = "🔒" if not c.reschedulable else "  "
        lines.append(
            f"  {lock} {c.time_slot.pretty():<25}  {c.title}  (priority {c.priority})"
        )
    return "\n".join(lines)
