"""
mcp_server.py — MCP server exposing routine tools.

This runs as a separate process for MCP clients (Claude Desktop, etc.).
The web chatbot uses the same logic directly (no transport overhead).

Usage:
  python mcp_server.py          # starts stdio transport (for MCP hosts)
  mcp dev mcp_server.py         # starts inspector for debugging
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List

from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("routine-agent")


# ── Schedule tools ────────────────────────────────────────────────────────────

@mcp.tool()
def get_routine_summary() -> str:
    """Get a full summary of all scheduled commitments."""
    from routine_manager import load_routine
    commitments = load_routine("routine.json")
    if not commitments:
        return "No commitments found."
    lines = []
    for c in commitments:
        days = ", ".join(d.value for d in c.days)
        lock = " [fixed]" if not c.reschedulable else ""
        lines.append(f"{c.title}: {days}, {c.time_slot.pretty()}{lock} (priority {c.priority})")
    return "\n".join(lines)


@mcp.tool()
def get_free_slots_for_today(duration_minutes: int = 60) -> List[str]:
    """Get free time slots for today."""
    from availability import get_free_slots
    from routine_manager import load_routine
    commitments = load_routine("routine.json")
    slots = get_free_slots(date.today(), commitments, duration_minutes=duration_minutes)
    return [s.pretty() for s in slots[:6]]


@mcp.tool()
def check_availability(time_str: str, duration_minutes: int = 60) -> Dict[str, Any]:
    """
    Check if the user is free at a given time today.

    Args:
        time_str: Time like '20:00', '8pm', 'evening'
        duration_minutes: How long the slot needs to be
    """
    import re
    from datetime import datetime, timedelta
    from availability import is_slot_free
    from models import TimeSlot
    from routine_manager import load_routine

    # Parse time
    s = time_str.strip().lower()
    word_map = {"morning": "09:00", "noon": "12:00", "afternoon": "14:00",
                "evening": "18:00", "night": "20:00"}
    for word, t in word_map.items():
        if word in s:
            start = datetime.strptime(t, "%H:%M").time()
            break
    else:
        m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
        if not m:
            return {"free": None, "error": f"Cannot parse time: {time_str}"}
        h, mins = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) == "pm" and h != 12: h += 12
        if m.group(3) == "am" and h == 12: h = 0
        start = datetime.strptime(f"{h:02d}:{mins:02d}", "%H:%M").time()

    end_dt = datetime.combine(date.today(), start) + timedelta(minutes=duration_minutes)
    slot = TimeSlot(start=start, end=end_dt.time())
    commitments = load_routine("routine.json")
    is_free, conflict = is_slot_free(date.today(), slot, commitments)

    return {
        "free": is_free,
        "slot": slot.pretty(),
        "conflict": conflict.title if conflict else None,
        "conflict_priority": conflict.priority if conflict else None,
        "conflict_reschedulable": conflict.reschedulable if conflict else None,
    }


@mcp.tool()
def add_commitment_to_routine(
    title: str,
    time_str: str,
    days: List[str],
    commitment_type: str = "work_meeting",
    duration_minutes: int = 60,
) -> str:
    """
    Add a new recurring commitment to the routine.

    Args:
        title: Name of the commitment
        time_str: Start time like '20:00' or '8pm'
        days: List of days like ['monday', 'wednesday'] or ['weekdays']
        commitment_type: gym, class, deep_work, work_meeting, lunch
        duration_minutes: Length in minutes
    """
    import re
    from datetime import datetime, timedelta
    from models import Commitment, TimeSlot, DayOfWeek
    from routine_manager import load_routine, save_routine
    from config_loader import Config

    config = Config("config.yaml")
    s = time_str.strip().lower()
    word_map = {"morning": "09:00", "noon": "12:00", "afternoon": "14:00",
                "evening": "18:00", "night": "20:00"}
    for word, t in word_map.items():
        if word in s:
            start = datetime.strptime(t, "%H:%M").time()
            break
    else:
        m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
        if not m:
            return f"Cannot parse time: {time_str}"
        h, mins = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) == "pm" and h != 12: h += 12
        if m.group(3) == "am" and h == 12: h = 0
        start = datetime.strptime(f"{h:02d}:{mins:02d}", "%H:%M").time()

    # Expand day shortcuts
    expanded = []
    for d in days:
        dl = d.lower()
        if dl in ("weekdays", "weekday"):
            expanded += ["monday","tuesday","wednesday","thursday","friday"]
        elif dl in ("everyday", "daily"):
            expanded += ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
        elif dl == "weekend":
            expanded += ["saturday","sunday"]
        else:
            expanded.append(dl)

    day_enums = []
    for d in expanded:
        try: day_enums.append(DayOfWeek(d))
        except ValueError: pass
    if not day_enums:
        return f"No valid days in {days}"

    end_dt = datetime.combine(date.today(), start) + timedelta(minutes=duration_minutes)
    cfg = config.get_commitment_config(commitment_type)
    new_c = Commitment(
        id=f"{title.lower().replace(' ','-')}-mcp",
        title=title,
        commitment_type=commitment_type,
        days=day_enums,
        time_slot=TimeSlot(start=start, end=end_dt.time()),
        priority=cfg.get("priority", 5),
        reschedulable=cfg.get("reschedulable", True),
    )
    existing = load_routine("routine.json")
    existing = [c for c in existing if c.title.lower() != title.lower()]
    existing.append(new_c)
    save_routine(existing, "routine.json")
    days_str = ", ".join(d.value for d in day_enums)
    return f"Added '{title}' every {days_str} at {new_c.time_slot.pretty()}."


@mcp.tool()
def get_configured_requesters() -> Dict[str, Any]:
    """Show all known requesters and their priority levels from config."""
    import yaml
    with open("config.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("requesters", {})


@mcp.tool()
def health_check() -> Dict[str, str]:
    """Check which services are configured."""
    return {
        "status": "ok",
        "service": "routine-agent-mcp",
        "anthropic": "configured" if os.getenv("ANTHROPIC_API_KEY") else "missing",
        "slack": "configured" if os.getenv("SLACK_BOT_TOKEN") else "missing",
        "gmail": "configured" if os.getenv("GMAIL_CLIENT_ID") else "missing",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
