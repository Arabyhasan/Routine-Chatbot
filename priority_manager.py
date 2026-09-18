from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from config_loader import Config
from models import Commitment, SchedulingDecision, MeetingRequest, RequesterProfile, TimeSlot
from priority import handle_meeting_request


@dataclass
class PriorityDecision:
    accepted: bool
    action: str
    target: Optional[str]
    reason: str


class PriorityManager:
    """High-level priority policy for multi-request conflicts and email/Slack priority rules."""

    def __init__(self, config: Config):
        self.config = config

    def score_requester(self, requester: RequesterProfile) -> int:
        return requester.priority

    def choose_priority_request(self, requests: List[MeetingRequest]) -> MeetingRequest:
        return max(requests, key=lambda r: self.config.get_requester(r.requester_id)["priority"])

    def should_postpone_lower_priority(self, incoming: MeetingRequest, existing: MeetingRequest) -> bool:
        incoming_priority = self.config.get_requester(incoming.requester_id)["priority"]
        existing_priority = self.config.get_requester(existing.requester_id)["priority"]
        return incoming_priority > existing_priority

    def decide_conflict(self, incoming: MeetingRequest, alternatives: List[TimeSlot]) -> PriorityDecision:
        requester = self.config.get_requester(incoming.requester_id)
        if requester["priority"] >= self.config.manager_override_threshold:
            return PriorityDecision(True, "resolve_as_priority", None, "High-priority requester accepted.")
        return PriorityDecision(False, "offer_alternatives", None, "Lower-priority request; alternative slots offered.")
