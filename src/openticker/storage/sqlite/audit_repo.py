"""write_audit, list_audit: the append-only audit log."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import AuditLogRow


@dataclass(frozen=True)
class AuditEntry:
    id: int
    occurred_at: datetime  # tz-aware UTC
    event_type: str
    triggered_by: str | None
    payload: str  # JSON


def write_audit(
    event_type: str, occurred_at: datetime, triggered_by: str | None, payload: str
) -> None:
    row = AuditLogRow(
        occurred_at=occurred_at.astimezone(UTC).replace(tzinfo=None),
        event_type=event_type,
        triggered_by=triggered_by,
        payload=payload,
    )
    with Session(get_engine()) as session:
        session.add(row)
        session.commit()


def list_audit(limit: int, event_type: str | None = None) -> list[AuditEntry]:
    """Most recent first."""
    statement = select(AuditLogRow).order_by(AuditLogRow.id.desc()).limit(limit)
    if event_type is not None:
        statement = statement.where(AuditLogRow.event_type == event_type)
    with Session(get_engine()) as session:
        rows = session.scalars(statement).all()
    return [
        AuditEntry(
            id=row.id,
            occurred_at=row.occurred_at.replace(tzinfo=UTC),
            event_type=row.event_type,
            triggered_by=row.triggered_by,
            payload=row.payload,
        )
        for row in rows
    ]
