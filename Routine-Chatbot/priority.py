"""
priority.py — The brain of the Routine Agent.

All decision logic lives here. The rule structure is:

  1. Is the requested slot free?
       → YES: confirm immediately
       → NO:  check if we can override the conflict

  2. Can we override?
       Requires ALL THREE conditions to be true:
         a) requester.priority >= manager_override_threshold   (who is asking?)
         b) conflict.reschedulable == True                     (can it move?)
         c) conflict.priority <= max_reschedulable_priority    (is it important enough to protect?)

       → YES: reschedule the commitment, confirm the meeting
       → NO:  decline and offer free-slot alternatives

Changing the rules = editing config.yaml only. No code change needed.
"""
from __future__ import annotations
from datetime import date
from typing import List

from models import (
    MeetingRequest, Commitment, SchedulingDecision,
    TimeSlot, RequesterProfile,
)
from config_loader import Config
from availability import get_free_slots, is_slot_free
from routine_manager import load_routine


def _build_requester(config: Config, requester_id: str) -> RequesterProfile:
    data = config.get_requester(requester_id)
    return RequesterProfile(
        requester_id=requester_id,
        display_name=data["display_name"],
        priority=data["priority"],
        relationship=data["relationship"],
    )


def _confirm(requester: RequesterProfile, slot: TimeSlot) -> SchedulingDecision:
    return SchedulingDecision(
        action="confirm",
        confirmed_slot=slot,
        rescheduled_commitment=None,
        alternative_slots=[],
        reply_message=(
            f"Hi {requester.display_name}! ✅ That time works for me — "
            f"{slot.pretty()}. I'll add it to the calendar."
        ),
        reasoning="Requested slot is free. Confirming directly.",
    )


def _resolve_conflict(
    request: MeetingRequest,
    requester: RequesterProfile,
    conflict: Commitment,
    all_commitments: List[Commitment],
    target_date: date,
    config: Config,
) -> SchedulingDecision:
    """
    Decide what to do when the requested slot conflicts with an existing commitment.
    """
    # ── Override check ─────────────────────────────────────────────────────
    high_priority_requester = requester.priority >= config.manager_override_threshold
    commitment_can_move     = conflict.reschedulable
    commitment_not_sacred   = conflict.priority <= config.max_reschedulable_priority

    can_override = high_priority_requester and commitment_can_move and commitment_not_sacred

    if can_override:
        slot = request.requested_time_slot
        reasoning = (
            f"Override approved: {requester.display_name} (priority {requester.priority}) "
            f">= threshold ({config.manager_override_threshold}). "
            f"'{conflict.title}' (priority {conflict.priority}) is reschedulable "
            f"and below the sacred threshold ({config.max_reschedulable_priority})."
        )
        reply = (
            f"Hi {requester.display_name}! ✅ Confirmed for {slot.pretty()}. "
            f"I've moved my {conflict.title} to free that slot up — see you then!"
        )
        return SchedulingDecision(
            action="reschedule_and_confirm",
            confirmed_slot=slot,
            rescheduled_commitment=conflict,
            alternative_slots=[],
            reply_message=reply,
            reasoning=reasoning,
        )

    # ── Can't override — decline and offer alternatives ────────────────────
    free_slots   = get_free_slots(target_date, all_commitments, request.duration_minutes)
    alternatives = free_slots[: config.alternative_slots_count]

    # Build readable alternative list
    if alternatives:
        alt_str = ", ".join(s.pretty() for s in alternatives)
        alt_part = f" Here are some times I'm free: {alt_str}."
    else:
        alt_part = " Unfortunately I have no other gaps today."

    # Explain WHY we declined (useful for debugging / supervisor demo)
    if not high_priority_requester:
        why = f"requester priority {requester.priority} < threshold {config.manager_override_threshold}"
    elif not commitment_can_move:
        why = f"'{conflict.title}' is marked reschedulable=false"
    else:
        why = f"'{conflict.title}' priority {conflict.priority} > max_reschedulable {config.max_reschedulable_priority}"

    reasoning = f"Declined: {why}."

    reply = (
        f"Hi {requester.display_name}, I have a conflict at that time "
        f"({conflict.title}, {conflict.time_slot.pretty()}).{alt_part} "
        f"Would any of those work for you?"
    )

    return SchedulingDecision(
        action="decline",
        confirmed_slot=None,
        rescheduled_commitment=None,
        alternative_slots=alternatives,
        reply_message=reply,
        reasoning=reasoning,
    )


def handle_meeting_request(
    request: MeetingRequest,
    target_date: date,
    config: Config,
    routine_path: str = "routine.json",
) -> SchedulingDecision:
    """
    Main entry point. Call this for every incoming Slack or Gmail meeting request.

    Args:
        request:      Parsed meeting request (from message_parser.py)
        target_date:  The date the meeting is requested for
        config:       Loaded Config object
        routine_path: Path to routine.json (injectable for tests)

    Returns:
        SchedulingDecision with action, reply, and reasoning
    """
    # Load once, pass through — no repeated file reads
    all_commitments = load_routine(routine_path)

    requester = _build_requester(config, request.requester_id)

    # If no time was parsed from the message, we can't proceed
    if not request.requested_time_slot:
        return SchedulingDecision(
            action="needs_clarification",
            confirmed_slot=None,
            rescheduled_commitment=None,
            alternative_slots=[],
            reply_message=f"Hi {requester.display_name}, could you let me know what time works for you?",
            reasoning="Could not parse a time from the message.",
        )

    is_free, conflict = is_slot_free(target_date, request.requested_time_slot, all_commitments)

    if is_free:
        return _confirm(requester, request.requested_time_slot)

    return _resolve_conflict(request, requester, conflict, all_commitments, target_date, config)
