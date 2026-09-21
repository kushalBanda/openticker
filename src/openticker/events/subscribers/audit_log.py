"""Writes every event to the audit log. Subscribed inline, so the record is
on disk before the publishing use case returns."""

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime

from openticker.storage.sqlite.audit_repo import write_audit


def record_event(event: object) -> None:
    fields = asdict(event) if is_dataclass(event) and not isinstance(event, type) else {}
    occurred_at = fields.pop("occurred_at", None)
    write_audit(
        event_type=type(event).__name__,
        occurred_at=occurred_at if isinstance(occurred_at, datetime) else datetime.now(UTC),
        triggered_by=fields.get("triggered_by"),
        payload=json.dumps(fields, default=str, sort_keys=True),
    )
