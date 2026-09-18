from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ServiceConfig:
    enabled_services: List[str] = field(default_factory=lambda: ["slack", "gmail", "calendar"])
    slack_enabled: bool = True
    gmail_enabled: bool = True
    calendar_enabled: bool = True
    login_mode: str = "interactive"
    slack_channel_ids: List[str] = field(default_factory=list)
    gmail_sender_filters: List[str] = field(default_factory=list)
    requester_priority_overrides: Dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        enabled = []
        for service in ("slack", "gmail", "calendar"):
            if os.getenv(f"ENABLE_{service.upper()}", "true").lower() == "true":
                enabled.append(service)

        return cls(
            enabled_services=enabled,
            slack_enabled="slack" in enabled,
            gmail_enabled="gmail" in enabled,
            calendar_enabled="calendar" in enabled,
            login_mode=os.getenv("LOGIN_MODE", "interactive"),
            slack_channel_ids=[item.strip() for item in os.getenv("SLACK_CHANNEL_IDS", "").split(",") if item.strip()],
            gmail_sender_filters=[item.strip() for item in os.getenv("GMAIL_SENDER_FILTERS", "").split(",") if item.strip()],
            requester_priority_overrides={
                key.strip(): int(value)
                for key, value in [item.split(":") for item in os.getenv("REQUESTER_PRIORITY_OVERRIDES", "").split(",") if ":" in item]
            },
        )


def prompt_service_selection() -> ServiceConfig:
    print("Choose the services to enable for this run:")
    print("1. Slack only")
    print("2. Gmail only")
    print("3. Slack + Gmail")
    print("4. Slack + Gmail + Calendar")
    print("5. Calendar only")

    choice = input("Enter option number: ").strip()
    mapping = {
        "1": ServiceConfig(enabled_services=["slack"], slack_enabled=True, gmail_enabled=False, calendar_enabled=False),
        "2": ServiceConfig(enabled_services=["gmail"], slack_enabled=False, gmail_enabled=True, calendar_enabled=False),
        "3": ServiceConfig(enabled_services=["slack", "gmail"], slack_enabled=True, gmail_enabled=True, calendar_enabled=False),
        "4": ServiceConfig(enabled_services=["slack", "gmail", "calendar"], slack_enabled=True, gmail_enabled=True, calendar_enabled=True),
        "5": ServiceConfig(enabled_services=["calendar"], slack_enabled=False, gmail_enabled=False, calendar_enabled=True),
    }
    return mapping.get(choice, ServiceConfig())
