"""Writes every event to the audit log. Subscribed inline, so the record is
on disk before the publishing use case returns."""

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any

from openticker.storage.sqlite.audit_repo import write_audit


def record_event(event: object) -> None:
    fields = asdict(event) if is_dataclass(event) and not isinstance(event, type) else {}
    occurred_at = fields.pop("occurred_at", None)
    write_audit(
        event_type=type(event).__name__,
        occurred_at=occurred_at if isinstance(occurred_at, datetime) else datetime.now(UTC),
        triggered_by=fields.get("triggered_by") or _actor(type(event).__name__, fields),
        payload=json.dumps(fields, default=str, sort_keys=True),
    )


def _actor(event_type: str, fields: dict[str, Any]) -> str | None:
    """Who did it, for an event that doesn't say (ADR 35): a strategy closes
    its own legs and ends its own run, a script its own process, a review
    job is the agent's, under its key's scope. The rest is the server itself."""
    if event_type == "AgentJobEnded":
        if fields.get("kind") == "debrief":
            return f"debrief:{fields['subject']}"
        return f"review:{fields['strategy_id']}"
    if event_type.startswith("Strategy") and "strategy_id" in fields:
        return f"strategy:{fields['strategy_id']}"
    if event_type.startswith("Script") and "script_id" in fields:
        return f"script:{fields['script_id']}"
    return None
