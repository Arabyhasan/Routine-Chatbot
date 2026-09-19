"""
mcp_tools.py — Single source of truth for all tool implementations.

Both the Claude agent (chatbot.py) and the MCP server (mcp_server.py) import
from here. Change a tool once — it's updated everywhere.

Flow:
  user message → Claude (orchestrator) → _execute_tool() → function here → result
                                                ↕
  mcp_server.py also calls these functions (thin wrappers around them)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from availability import get_free_slots, is_slot_free
from config_loader import Config
from models import Commitment, DayOfWeek, MeetingRequest, TimeSlot
from priority import handle_meeting_request
from routine_manager import load_routine, save_routine


# ─── Shared parsing helpers ───────────────────────────────────────────────────

def parse_time_str(time_str: str):
    """Parse natural time strings → datetime.time. Returns None if unparseable."""
    s = (time_str or "").strip().lower()
    word_map = {
        "morning": "09:00", "noon": "12:00", "afternoon": "14:00",
        "evening": "18:00", "night": "20:00", "tonight": "20:00", "midnight": "00:00",
    }
    for word, t in word_map.items():
        if word in s:
            return datetime.strptime(t, "%H:%M").time()

    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)}:{m.group(2)}", "%H:%M").time()
        except ValueError:
            pass

    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", s)
    if m:
        h, mins = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) == "pm" and h != 12:
            h += 12
        if m.group(3) == "am" and h == 12:
            h = 0
        try:
            return datetime.strptime(f"{h:02d}:{mins:02d}", "%H:%M").time()
        except ValueError:
            pass

    m = re.match(r"^(\d{1,2})$", s)
    if m:
        h = int(m.group(1))
        if 1 <= h <= 6:
            h += 12  # 1–6 → PM
        try:
            return datetime.strptime(f"{h:02d}:00", "%H:%M").time()
        except ValueError:
            pass

    return None


def parse_day_str(day_str: str) -> date:
    """Parse 'today', 'tomorrow', 'monday', etc. → date."""
    s = (day_str or "today").strip().lower()
    today = date.today()
    if s in ("today", ""):
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if s in day_names:
        target = day_names.index(s)
        current = today.weekday()
        delta = (target - current) % 7 or 7
        return today + timedelta(days=delta)
    return today


def expand_day_shortcuts(days: list) -> list:
    """Expand 'weekdays', 'everyday', 'weekend' shortcuts."""
    result = []
    for d in days:
        s = str(d).lower()
        if s in ("weekdays", "weekday", "every weekday"):
            result += ["monday", "tuesday", "wednesday", "thursday", "friday"]
        elif s in ("everyday", "every day", "daily"):
            result += ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        elif s in ("weekend", "weekends"):
            result += ["saturday", "sunday"]
        else:
            result.append(s)
    return result


# ─── Tool context ─────────────────────────────────────────────────────────────

@dataclass
class ToolContext:
    """
    All the dependencies a tool might need, bundled in one place.
    Created once in RoutineChatbot.__init__ and passed to every tool call.
    This is dependency injection — tools don't reach for global state.
    """
    config: Config
    routine_path: str
    slack: Any = None
    google: Any = None
    knowledge_base: Any = None
    service_config: Any = None
    pending_email: Optional[dict] = None   # email draft awaiting user confirmation


# ─── Tool implementations ─────────────────────────────────────────────────────

def tool_read_schedule(ctx: ToolContext, inp: dict) -> str:
    target = parse_day_str(inp.get("day", "today"))
    day_enum = DayOfWeek(target.strftime("%A").lower())
    commitments = load_routine(ctx.routine_path)
    day_comms = sorted(
        [c for c in commitments if day_enum in c.days],
        key=lambda c: c.time_slot.start,
    )
    label = target.strftime("%A, %B %d")
    if not day_comms:
        return f"No commitments on {label} — completely free."
    lines = [f"Schedule for {label}:"]
    for c in day_comms:
        lock = " [cannot be moved]" if not c.reschedulable else ""
        lines.append(f"  • {c.time_slot.pretty():<25} {c.title}{lock} (priority {c.priority})")
    return "\n".join(lines)


def tool_check_time_slot(ctx: ToolContext, inp: dict) -> str:
    time_str = inp.get("time", "")
    duration = int(inp.get("duration_minutes", 60) or 60)
    start = parse_time_str(time_str)
    if start is None:
        return f"Couldn't parse time '{time_str}'. Use format like '8pm' or '20:00'."
    end_dt = datetime.combine(date.today(), start) + timedelta(minutes=duration)
    slot = TimeSlot(start=start, end=end_dt.time())
    target = parse_day_str(inp.get("day", "today"))
    is_free, conflict = is_slot_free(target, slot, load_routine(ctx.routine_path))
    if is_free:
        return f"{slot.pretty()} on {target.strftime('%A')} is free."
    return (
        f"Conflict: '{conflict.title}' at {conflict.time_slot.pretty()} on {target.strftime('%A')}. "
        f"Priority: {conflict.priority}, moveable: {conflict.reschedulable}."
    )


def tool_get_free_slots(ctx: ToolContext, inp: dict) -> str:
    day_str = inp.get("day", "today")
    duration = int(inp.get("duration_minutes", 60) or 60)
    target = parse_day_str(day_str)
    commitments = load_routine(ctx.routine_path)
    slots = get_free_slots(target, commitments, duration_minutes=duration)
    if not slots:
        return f"No free {duration}-minute gaps on {target.strftime('%A, %B %d')}."
    pretty = [s.pretty() for s in slots[:6]]
    return f"Free {duration}-min slots on {target.strftime('%A, %B %d')}: {', '.join(pretty)}."


def tool_schedule_meeting(ctx: ToolContext, inp: dict) -> str:
    title = inp.get("title", "Meeting")
    time_str = inp.get("time", "")
    duration = int(inp.get("duration_minutes", 60) or 60)
    requester_id = inp.get("requester_id", "unknown") or "unknown"
    day_str = inp.get("day", "today")

    start = parse_time_str(time_str)
    if start is None:
        return f"Couldn't parse time '{time_str}'."

    end_dt = datetime.combine(date.today(), start) + timedelta(minutes=duration)
    slot = TimeSlot(start=start, end=end_dt.time())
    target = parse_day_str(day_str)

    request = MeetingRequest(
        requester_id=requester_id,
        requester_name=requester_id,
        channel="chat",
        message_text=title,
        requested_date=target,
        requested_time_slot=slot,
        duration_minutes=duration,
    )
    decision = handle_meeting_request(request, target, ctx.config, ctx.routine_path)

    # Write confirmed meetings to routine
    if decision.action in ("confirm", "reschedule_and_confirm"):
        day_enum = DayOfWeek(target.strftime("%A").lower())
        new_c = Commitment(
            id=f"meeting-{title.lower().replace(' ', '-')}-{target}",
            title=title,
            commitment_type="work_meeting",
            days=[day_enum],
            time_slot=slot,
            priority=7,
            reschedulable=False,
            notes=f"Scheduled via assistant on {date.today()}",
        )
        existing = load_routine(ctx.routine_path)
        existing.append(new_c)
        save_routine(existing, ctx.routine_path)

    return (
        f"Action: {decision.action}. "
        f"{decision.reply_message} "
        f"(Reasoning: {decision.reasoning})"
    )


def tool_reschedule_commitment(ctx: ToolContext, inp: dict) -> str:
    title = inp.get("commitment_title", "")
    new_time_str = inp.get("new_time", "")
    commitments = load_routine(ctx.routine_path)

    match = next((c for c in commitments if c.title.lower() == title.lower()), None)
    if match is None:
        match = next((c for c in commitments if title.lower() in c.title.lower()), None)
    if match is None:
        names = ", ".join(c.title for c in commitments)
        return f"No commitment named '{title}'. Existing: {names}."

    new_start = parse_time_str(new_time_str)
    if new_start is None:
        return f"Couldn't parse new time '{new_time_str}'."

    old_pretty = match.time_slot.pretty()
    old_dur = match.time_slot.duration_minutes()
    end_dt = datetime.combine(date.today(), new_start) + timedelta(minutes=old_dur)
    match.time_slot = TimeSlot(start=new_start, end=end_dt.time())
    match.notes = f"Rescheduled from {old_pretty} via assistant."
    save_routine(commitments, ctx.routine_path)
    return f"Moved '{match.title}' from {old_pretty} to {match.time_slot.pretty()}."


def tool_cancel_commitment(ctx: ToolContext, inp: dict) -> str:
    title = inp.get("commitment_title", "")
    commitments = load_routine(ctx.routine_path)
    updated = [c for c in commitments if c.title.lower() != title.lower()]
    if len(updated) == len(commitments):
        updated = [c for c in commitments if title.lower() not in c.title.lower()]
    if len(updated) == len(commitments):
        names = ", ".join(c.title for c in commitments)
        return f"No commitment named '{title}'. Existing: {names}."
    removed = len(commitments) - len(updated)
    save_routine(updated, ctx.routine_path)
    return f"Removed {removed} commitment(s) matching '{title}'."


def tool_add_recurring_commitment(ctx: ToolContext, inp: dict) -> str:
    title = inp.get("title", "New Commitment")
    time_str = inp.get("time", "09:00")
    days_raw = expand_day_shortcuts(inp.get("days", ["monday"]))
    commitment_type = inp.get("commitment_type", "work_meeting")
    duration = int(inp.get("duration_minutes", 60) or 60)

    start = parse_time_str(time_str)
    if start is None:
        return f"Couldn't parse time '{time_str}'."

    day_enums = []
    for d in days_raw:
        try:
            day_enums.append(DayOfWeek(d.lower()))
        except ValueError:
            pass
    if not day_enums:
        return f"No valid days in {inp.get('days', [])}. Use: monday, tuesday, ..., everyday, weekdays."

    end_dt = datetime.combine(date.today(), start) + timedelta(minutes=duration)
    cfg = ctx.config.get_commitment_config(commitment_type)
    new_c = Commitment(
        id=f"{title.lower().replace(' ', '-')}-recurring",
        title=title,
        commitment_type=commitment_type,
        days=day_enums,
        time_slot=TimeSlot(start=start, end=end_dt.time()),
        priority=cfg.get("priority", 5),
        reschedulable=cfg.get("reschedulable", True),
        notes=f"Added via assistant on {date.today()}",
    )
    existing = load_routine(ctx.routine_path)
    existing = [c for c in existing if c.title.lower() != title.lower()]
    existing.append(new_c)
    save_routine(existing, ctx.routine_path)
    days_str = ", ".join(d.value for d in day_enums)
    return f"Added '{title}' every {days_str} at {new_c.time_slot.pretty()}."


def tool_send_slack_message(ctx: ToolContext, inp: dict) -> str:
    if ctx.slack is None or not getattr(ctx.slack, "bot_token", None):
        return "Slack not configured — add SLACK_BOT_TOKEN to .env."
    channel = inp.get("channel", "meeting-times").lstrip("#")
    message = inp.get("message", "")
    if not message:
        return "No message provided."
    try:
        channel_id = ctx.slack.resolve_channel_id(channel)
        if not channel_id:
            channels = getattr(ctx.service_config, "slack_channel_ids", []) or []
            for cid in channels:
                channel_id = ctx.slack.resolve_channel_id(cid)
                if channel_id:
                    break
        if not channel_id:
            return f"Couldn't find Slack channel '{channel}'. Check the channel name."
        ctx.slack.send_message(channel_id, message)
        return f"Sent to #{channel}: \"{message}\""
    except Exception as exc:
        return f"Slack error: {exc}"


def tool_send_email(ctx: ToolContext, inp: dict) -> str:
    """Draft an email; set send_now=True only if user explicitly said to send."""
    to_email = inp.get("to_email", "")
    subject = inp.get("subject", "Message from your assistant")
    context_text = inp.get("context", "")
    send_now = bool(inp.get("send_now", False))

    if not re.match(r"[^@]+@[^@]+\.[^@]+", to_email):
        return f"Invalid email address: '{to_email}'"

    from email_agent import EmailAgent
    agent = EmailAgent()
    draft = agent.draft_email(to_email, subject, context_text)

    # Store draft so user can confirm/cancel via confirm_pending_email tool
    ctx.pending_email = {
        "to_email": to_email,
        "subject": subject,
        "draft": draft,
    }

    if send_now and ctx.google and getattr(ctx.google, "creds", None):
        try:
            ctx.google.send_email(to_email, subject, draft)
            ctx.pending_email = None
            return f"Email sent to {to_email}.\n\nSubject: {subject}\n\n{draft}"
        except Exception as exc:
            return f"Draft ready but send failed: {exc}\n\nDraft:\nSubject: {subject}\n\n{draft}"

    return (
        f"Draft ready for {to_email}:\n\n"
        f"Subject: {subject}\n\n{draft}\n\n"
        f"Reply 'send it' to send, or 'cancel' to discard."
    )


def tool_confirm_pending_email(ctx: ToolContext, inp: dict) -> str:
    confirm = (inp.get("confirm") or "").strip().lower()
    if not ctx.pending_email:
        return "No pending email draft to confirm."
    if confirm in ("yes", "send", "send it", "confirm", "approve"):
        pending = ctx.pending_email
        ctx.pending_email = None
        if ctx.google and getattr(ctx.google, "creds", None):
            try:
                ctx.google.send_email(pending["to_email"], pending["subject"], pending["draft"])
                return f"Email sent to {pending['to_email']}."
            except Exception as exc:
                return f"Send failed: {exc}"
        return f"Gmail not connected. Here's the draft to copy:\n\n{pending['draft']}"
    ctx.pending_email = None
    return "Email cancelled."


def tool_remember_fact(ctx: ToolContext, inp: dict) -> str:
    fact = inp.get("fact", "")
    category = inp.get("category", "preferences")
    if not fact:
        return "No fact provided."
    if ctx.knowledge_base:
        try:
            ctx.knowledge_base.store(category, fact)
            return f"Remembered: {fact}"
        except Exception as exc:
            return f"Could not save to knowledge base: {exc}"
    return f"(Knowledge base not connected) Noted: {fact}"


def tool_recall_memory(ctx: ToolContext, inp: dict) -> str:
    if ctx.knowledge_base:
        try:
            return ctx.knowledge_base.recall_all() or "Nothing stored yet."
        except Exception as exc:
            return f"Could not read knowledge base: {exc}"
    return "Knowledge base not connected."


def tool_get_configured_requesters(ctx: ToolContext, inp: dict) -> str:
    try:
        import yaml
        config_path = getattr(ctx.config, "_path", "config.yaml")
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        requesters = raw.get("requesters", {})
        lines = []
        for key, data in requesters.items():
            if key == "default_unknown":
                lines.append(f"  unknown: priority {data['priority']}")
            else:
                lines.append(f"  {data.get('display_name', key)}: priority {data['priority']} ({data.get('relationship', '')})")
        return "Configured requesters:\n" + "\n".join(lines)
    except Exception as exc:
        return f"Could not read requesters: {exc}"


def tool_health_check(ctx: ToolContext, inp: dict) -> str:
    parts = [
        f"Claude API: {'configured' if os.getenv('ANTHROPIC_API_KEY') else 'MISSING'}",
        f"Slack: {'ready' if (ctx.slack and getattr(ctx.slack, 'bot_token', None)) else 'not configured'}",
        f"Gmail: {'ready' if (ctx.google and getattr(ctx.google, 'creds', None)) else 'not configured'}",
        f"Routine: {len(load_routine(ctx.routine_path))} commitment(s)",
    ]
    return "\n".join(parts)


# ─── Dispatch table ───────────────────────────────────────────────────────────
# Used by both chatbot.py and mcp_server.py

TOOL_DISPATCH: dict = {
    "read_schedule":            tool_read_schedule,
    "check_time_slot":          tool_check_time_slot,
    "get_free_slots":           tool_get_free_slots,
    "schedule_meeting":         tool_schedule_meeting,
    "reschedule_commitment":    tool_reschedule_commitment,
    "cancel_commitment":        tool_cancel_commitment,
    "add_recurring_commitment": tool_add_recurring_commitment,
    "send_slack_message":       tool_send_slack_message,
    "send_email":               tool_send_email,
    "confirm_pending_email":    tool_confirm_pending_email,
    "remember_fact":            tool_remember_fact,
    "recall_memory":            tool_recall_memory,
    "get_configured_requesters": tool_get_configured_requesters,
    "health_check":             tool_health_check,
}


def execute(ctx: ToolContext, tool_name: str, tool_input: dict) -> str:
    """Single entry point for both chatbot.py and mcp_server.py."""
    fn = TOOL_DISPATCH.get(tool_name)
    if fn is None:
        return f"Unknown tool: {tool_name}"
    try:
        return str(fn(ctx, tool_input))
    except Exception as exc:
        return f"Tool '{tool_name}' error: {exc}"
