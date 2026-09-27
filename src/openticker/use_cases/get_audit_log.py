"""Audit log entries, most recent first, filtered and paged."""

from collections.abc import Sequence
from datetime import date, datetime, time

from openticker.core.pnl import Source
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage.sqlite.audit_repo import AuditEntry, list_audit


def get_audit_log(
    limit: int,
    event_type: str | None = None,
    *,
    event_types: Sequence[str] = (),
    source: Source | None = None,
    from_date: date | None = None,
    before_id: int | None = None,
) -> list[AuditEntry]:
    """`from_date` is an exchange-local day: entries from its midnight on."""
    since = (
        datetime.combine(from_date, time(), EXCHANGE_TIMEZONE) if from_date is not None else None
    )
    return list_audit(
        limit,
        event_type,
        event_types=event_types,
        source=source,
        since=since,
        before_id=before_id,
    )


def new_audit_entries(after_id: int, limit: int) -> list[AuditEntry]:
    """Entries after `after_id`, oldest first: what the stream sends next."""
    return list_audit(limit, after_id=after_id, oldest_first=True)


def latest_audit_id() -> int:
    """The newest entry's id; 0 when the log is empty."""
    latest = list_audit(1)
    return latest[0].id if latest else 0
