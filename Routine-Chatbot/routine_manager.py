"""
routine_manager.py — All reads and writes to your routine file.

Currently: JSON file on disk.
To swap to Google Sheets: replace load_routine() and save_routine() only.
Everything else in the codebase stays the same — that's the whole point.

Google Sheets swap plan (when you're ready):
  1. pip install gspread google-auth
  2. Replace load_routine() with a gspread.open_by_key() call
  3. Replace save_routine() with worksheet.update() call
  4. The rest of the agent is untouched
"""
from __future__ import annotations
import json
import uuid
from datetime import time
from pathlib import Path
from typing import List, Optional

from models import Commitment, TimeSlot, DayOfWeek

ROUTINE_PATH = "routine.json"


def _parse_time(t: str) -> time:
    h, m = map(int, t.split(":"))
    return time(h, m)


def _time_str(t: time) -> str:
    return t.strftime("%H:%M")


def load_routine(path: str = ROUTINE_PATH) -> List[Commitment]:
    """Load all commitments from the routine file."""
    p = Path(path)
    if not p.exists():
        return []

    with open(p) as f:
        data = json.load(f)

    commitments = []
    for item in data.get("commitments", []):
        slot = TimeSlot(
            start=_parse_time(item["start_time"]),
            end=_parse_time(item["end_time"]),
        )
        c = Commitment(
            id=item["id"],
            title=item["title"],
            commitment_type=item["type"],
            days=[DayOfWeek(d) for d in item["days"]],
            time_slot=slot,
            priority=item["priority"],
            reschedulable=item.get("reschedulable", True),
            notes=item.get("notes", ""),
            calendar_event_id=item.get("calendar_event_id"),
        )
        commitments.append(c)

    return commitments


def save_routine(commitments: List[Commitment], path: str = ROUTINE_PATH):
    """Write commitments back to the routine file (full overwrite)."""
    data = {
        "version": 1,
        "commitments": [
            {
                "id":               c.id,
                "title":            c.title,
                "type":             c.commitment_type,
                "days":             [d.value for d in c.days],
                "start_time":       _time_str(c.time_slot.start),
                "end_time":         _time_str(c.time_slot.end),
                "priority":         c.priority,
                "reschedulable":    c.reschedulable,
                "notes":            c.notes,
                "calendar_event_id": c.calendar_event_id,
            }
            for c in commitments
        ],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def add_commitment(new: Commitment, path: str = ROUTINE_PATH):
    """Append a new commitment; auto-generates ID if empty."""
    if not new.id:
        new.id = str(uuid.uuid4())[:8]
    existing = load_routine(path)
    existing.append(new)
    save_routine(existing, path)


def remove_commitment(commitment_id: str, path: str = ROUTINE_PATH):
    """Remove a commitment by ID (used when rescheduling)."""
    existing = load_routine(path)
    updated = [c for c in existing if c.id != commitment_id]
    save_routine(updated, path)


def get_commitments_for_day(day: DayOfWeek, path: str = ROUTINE_PATH) -> List[Commitment]:
    """Return all commitments that apply to a specific weekday."""
    return [c for c in load_routine(path) if day in c.days]
