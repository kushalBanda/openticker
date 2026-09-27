"""write_audit, list_audit: the append-only audit log."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, and_, false, not_, or_, select
from sqlalchemy.orm import Session

from openticker.core.pnl import RULES, Rule, Source
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


def list_audit(
    limit: int,
    event_type: str | None = None,
    *,
    event_types: Sequence[str] = (),
    source: Source | None = None,
    since: datetime | None = None,
    before_id: int | None = None,
    after_id: int | None = None,
    oldest_first: bool = False,
) -> list[AuditEntry]:
    """Most recent first, unless `oldest_first` (the stream's tail reads
    forward from `after_id`). `before_id` pages back through older entries."""
    statement = select(AuditLogRow).limit(limit)
    statement = statement.order_by(AuditLogRow.id.asc() if oldest_first else AuditLogRow.id.desc())
    kinds = [*event_types, *([event_type] if event_type is not None else [])]
    if kinds:
        statement = statement.where(AuditLogRow.event_type.in_(kinds))
    if source is not None:
        statement = statement.where(_by(source))
    if since is not None:
        statement = statement.where(
            AuditLogRow.occurred_at >= since.astimezone(UTC).replace(tzinfo=None)
        )
    if before_id is not None:
        statement = statement.where(AuditLogRow.id < before_id)
    if after_id is not None:
        statement = statement.where(AuditLogRow.id > after_id)
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


def _matches(rule: Rule) -> ColumnElement[bool]:
    column = AuditLogRow.triggered_by
    if rule.prefix:
        return column.startswith(rule.text, autoescape=True)
    return column == rule.text


def _by(source: Source) -> ColumnElement[bool]:
    """Entries whose `triggered_by` reads as `source`: the rules `source_of`
    applies, in the same order (a rule counts only where no earlier one
    matched)."""
    if source is Source.SYSTEM:
        return or_(AuditLogRow.triggered_by.is_(None), not_(or_(*(_matches(r) for r in RULES))))
    wanted = [
        and_(_matches(rule), *(not_(_matches(earlier)) for earlier in RULES[:i]))
        for i, rule in enumerate(RULES)
        if rule.source is source
    ]
    return or_(false(), *wanted)
