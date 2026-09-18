from __future__ import annotations

import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("routine-agent")


@mcp.tool()
def get_routine_summary() -> str:
    """Return a quick summary of the local routine JSON file."""
    from routine_manager import load_routine

    commitments = load_routine("routine.json")
    if not commitments:
        return "No commitments loaded."

    summary = []
    for c in commitments:
        summary.append(f"{c.title}: {c.time_slot.pretty()} on {', '.join(d.value for d in c.days)}")
    return "\n".join(summary)


@mcp.tool()
def get_free_slots_for_today() -> List[str]:
    """Return the demo free slots for today using the same scheduling logic."""
    from datetime import date
    from availability import get_free_slots
    from routine_manager import load_routine

    commitments = load_routine("routine.json")
    slots = get_free_slots(date.today(), commitments, duration_minutes=60)
    return [slot.pretty() for slot in slots[:5]]


@mcp.tool()
def get_configured_requesters() -> Dict[str, Any]:
    """Expose requester metadata as an MCP tool."""
    import yaml

    with open("config.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("requesters", {})


@mcp.tool()
def health_check() -> Dict[str, str]:
    """Simple server health check for local testing."""
    return {
        "status": "ok",
        "service": "routine-agent-mcp",
        "slack_configured": bool(os.getenv("SLACK_BOT_TOKEN")),
        "gmail_configured": bool(os.getenv("GMAIL_CLIENT_ID") and os.getenv("GMAIL_CLIENT_SECRET")),
        "calendar_configured": bool(os.getenv("GOOGLE_CALENDAR_CREDENTIALS_PATH")),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
