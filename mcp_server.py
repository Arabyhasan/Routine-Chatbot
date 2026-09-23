"""
mcp_server.py — MCP server. Thin wrappers around mcp_tools.py.

The actual logic lives in mcp_tools.py — both this file and chatbot.py
call the same functions. Change a tool once, updated everywhere.

Usage:
  python mcp_server.py          # stdio transport (for Claude Desktop / MCP hosts)
  mcp dev mcp_server.py         # MCP inspector for debugging
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from env_loader import load_project_env
load_project_env()

from mcp_tools import ToolContext, execute as _execute
from config_loader import Config
from service_config import ServiceConfig

# The current MCP Python SDK calls its high-level server MCPServer. The web
# chatbot does not require MCP; this process is specifically for MCP hosts such
# as Claude Desktop.
from mcp.server import MCPServer

mcp = MCPServer("routine-agent")


def _ctx() -> ToolContext:
    """Build a ToolContext for each MCP call (stateless — no persistent connection)."""
    svc = ServiceConfig.from_env()
    slack = None
    google = None
    if svc.slack_enabled:
        try:
            from slack_integration import SlackIntegration
            slack = SlackIntegration()
        except Exception:
            pass
    if svc.gmail_enabled or svc.calendar_enabled:
        try:
            from google_integration import GoogleIntegration
            google = GoogleIntegration()
        except Exception:
            pass
    knowledge_base = None
    try:
        from knowledge_base import UserKnowledgeBase
        knowledge_base = UserKnowledgeBase("knowledge_store.json")
    except Exception:
        pass
    return ToolContext(
        config=Config("config.yaml"),
        routine_path="routine.json",
        slack=slack,
        google=google,
        knowledge_base=knowledge_base,
        service_config=svc,
    )


def _call(tool_name: str, **kwargs) -> str:
    return _execute(_ctx(), tool_name, kwargs)


# ─── MCP tool registrations ───────────────────────────────────────────────────

@mcp.tool()
def read_schedule(day: str = "today") -> str:
    """Get the user's schedule for a specific day."""
    return _call("read_schedule", day=day)

@mcp.tool()
def check_time_slot(time: str, duration_minutes: int = 60, day: str = "today") -> str:
    """Check if the user is free at a given time."""
    return _call("check_time_slot", time=time, duration_minutes=duration_minutes, day=day)

@mcp.tool()
def check_availability(time_str: str, duration_minutes: int = 60) -> Dict[str, Any]:
    """Check availability — alias used by some MCP clients."""
    text = _call("check_time_slot", time=time_str, duration_minutes=duration_minutes, day="today")
    return {"result": text}

@mcp.tool()
def get_free_slots(day: str = "today", duration_minutes: int = 60) -> str:
    """List free time slots on a given day."""
    return _call("get_free_slots", day=day, duration_minutes=duration_minutes)

@mcp.tool()
def get_free_slots_for_today(duration_minutes: int = 60) -> List[str]:
    """Get free slots for today (convenience alias)."""
    return [_call("get_free_slots", day="today", duration_minutes=duration_minutes)]

@mcp.tool()
def get_weather(city: str) -> str:
    """Get live current weather for a city, such as 'Dhaka, Bangladesh'."""
    return _call("get_weather", city=city)

@mcp.tool()
def schedule_meeting(
    title: str,
    time: str,
    duration_minutes: int = 60,
    requester_id: str = "unknown",
    day: str = "today",
) -> str:
    """Schedule a meeting through the priority engine."""
    return _call("schedule_meeting", title=title, time=time,
                 duration_minutes=duration_minutes, requester_id=requester_id, day=day)

@mcp.tool()
def reschedule_commitment(commitment_title: str, new_time: str) -> str:
    """Move an existing commitment to a new time."""
    return _call("reschedule_commitment", commitment_title=commitment_title, new_time=new_time)

@mcp.tool()
def cancel_commitment(commitment_title: str) -> str:
    """Remove a commitment from the routine."""
    return _call("cancel_commitment", commitment_title=commitment_title)

@mcp.tool()
def add_recurring_commitment(
    title: str,
    time: str,
    days: List[str],
    commitment_type: str = "work_meeting",
    duration_minutes: int = 60,
) -> str:
    """Add a new recurring commitment."""
    return _call("add_recurring_commitment", title=title, time=time, days=days,
                 commitment_type=commitment_type, duration_minutes=duration_minutes)

@mcp.tool()
def add_commitment_to_routine(
    title: str,
    time_str: str,
    days: List[str],
    commitment_type: str = "work_meeting",
    duration_minutes: int = 60,
) -> str:
    """Add a recurring commitment (alias with time_str param for compatibility)."""
    return _call("add_recurring_commitment", title=title, time=time_str, days=days,
                 commitment_type=commitment_type, duration_minutes=duration_minutes)

@mcp.tool()
def send_slack_message(channel: str, message: str) -> str:
    """Send a message to a Slack channel."""
    return _call("send_slack_message", channel=channel, message=message)

@mcp.tool()
def send_email(
    to_email: str,
    context: str,
    subject: str = "Message from your assistant",
    send_now: bool = False,
) -> str:
    """Draft (and optionally send) an email."""
    return _call("send_email", to_email=to_email, context=context,
                 subject=subject, send_now=send_now)

@mcp.tool()
def get_configured_requesters() -> str:
    """Show known requesters and their priority levels."""
    return _call("get_configured_requesters")

@mcp.tool()
def health_check() -> str:
    """Check which services are configured and working."""
    return _call("health_check")

@mcp.tool()
def confirm_pending_email(confirm: str) -> str:
    """Send or cancel the pending email draft after user confirmation ('yes' or 'no')."""
    return _call("confirm_pending_email", confirm=confirm)

@mcp.tool()
def remember_fact(fact: str, category: str = "preferences") -> str:
    """Store a user preference or personal fact for future reference."""
    return _call("remember_fact", fact=fact, category=category)

@mcp.tool()
def recall_memory() -> str:
    """Recall stored facts and preferences about the user."""
    return _call("recall_memory")

@mcp.tool()
def sync_to_sheets() -> str:
    """Sync the full weekly schedule to Google Sheets and return the sheet URL."""
    return _call("sync_to_sheets")


if __name__ == "__main__":
    mcp.run(transport="stdio")
