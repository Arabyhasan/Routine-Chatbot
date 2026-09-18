"""
config_loader.py — Loads config.yaml and gives typed access to every section.

Why a class and not just `yaml.safe_load()`?
  Because your controllers and tests import Config once and call named methods.
  If you rename a key in config.yaml, you fix it in ONE place here.
"""
from __future__ import annotations
import yaml
from pathlib import Path
from typing import Dict, Any, Optional


class Config:
    def __init__(self, config_path: str = "config.yaml"):
        path = Path(config_path)
        search_paths = [path] if path.is_absolute() else [
            Path.cwd() / path,
            Path(__file__).resolve().parent / path,
        ]

        resolved = next((candidate for candidate in search_paths if candidate.exists()), None)
        if resolved is None:
            raise FileNotFoundError(
                f"config.yaml not found in {', '.join(str(p) for p in search_paths)}. "
                "Make sure the project root contains config.yaml."
            )
        with open(resolved) as f:
            self._raw = yaml.safe_load(f)

    # ── Requester lookup ───────────────────────────────────────────────────

    def get_requester(self, identifier: str) -> Dict[str, Any]:
        """
        Look up a person by their Slack user ID or email.
        Returns their priority and relationship from config.
        Falls back to default_unknown if not found.
        """
        for key, data in self._raw["requesters"].items():
            if key == "default_unknown":
                continue
            ids = data.get("identifiers", {})
            if (
                identifier == ids.get("slack_user_id")
                or identifier.lower() == ids.get("email", "").lower()
                or identifier.lower() == key.lower()   # allow lookup by name in tests
            ):
                return {
                    "key":          key,
                    "priority":     data["priority"],
                    "display_name": data["display_name"],
                    "relationship": data["relationship"],
                }

        # Unknown sender — lowest priority
        default = self._raw["requesters"]["default_unknown"]
        return {
            "key":          "unknown",
            "priority":     default["priority"],
            "display_name": identifier,
            "relationship": "unknown",
        }

    # ── Commitment config ──────────────────────────────────────────────────

    def get_commitment_config(self, commitment_type: str) -> Dict[str, Any]:
        """Return priority + reschedulable for a commitment type."""
        return self._raw["commitments"].get(commitment_type, {
            "priority":     5,
            "reschedulable": False,
            "notes":        "",
        })

    # ── Conflict resolution thresholds ────────────────────────────────────

    @property
    def manager_override_threshold(self) -> int:
        """Requester must have AT LEAST this priority to override a commitment."""
        return self._raw["conflict_resolution"]["manager_override_threshold"]

    @property
    def max_reschedulable_priority(self) -> int:
        """A commitment with priority > this is never rescheduled, even for a manager."""
        return self._raw["conflict_resolution"]["max_reschedulable_priority"]

    @property
    def alternative_slots_count(self) -> int:
        return self._raw["conflict_resolution"]["alternative_slots_to_offer"]

    @property
    def timezone(self) -> str:
        return self._raw["agent"].get("timezone", "UTC")
