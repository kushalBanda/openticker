"""The desk manager's state and lines (ADR 41 in docs/adr). A missing state
row reads as off; NULLs read as their defaults (ADR 18)."""

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from openticker.core.agents.manager import (
    DEFAULT_WAKES_PER_DAY,
    OFF,
    LineKey,
    ManagerLine,
    ManagerPlan,
    ManagerState,
    SetBy,
    line_order,
    parse_key,
)
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import ManagerLineRow, ManagerStateRow

_ROW_ID = 1


def get_state(session: Session | None = None) -> ManagerState:
    if session is not None:
        return _state(session.get(ManagerStateRow, _ROW_ID))
    with Session(get_engine()) as own:
        return _state(own.get(ManagerStateRow, _ROW_ID))


def save_state(session: Session, state: ManagerState) -> None:
    row = session.get(ManagerStateRow, _ROW_ID)
    if row is None:
        row = ManagerStateRow(id=_ROW_ID, enabled=state.enabled)
        session.add(row)
    row.enabled = state.enabled
    row.wakes_per_day = (
        None if state.wakes_per_day == DEFAULT_WAKES_PER_DAY else state.wakes_per_day
    )
    row.next_wake_at = _naive(state.next_wake_at)
    row.next_wake_reason = state.next_wake_reason
    row.last_wake_at = _naive(state.last_wake_at)
    row.last_audit_id = state.last_audit_id
    row.crossed = json.dumps(sorted(state.crossed))
    row.closed_on = state.closed_on
    row.stalled = state.stalled
    plan = state.plan
    row.plan_day = plan.day if plan else None
    row.plan_text = plan.text if plan else None
    row.plan_lessons = json.dumps(list(plan.lesson_ids)) if plan else None
    row.plan_at = _naive(plan.at) if plan else None
    row.updated_at = _naive(state.updated_at)


def lines(session: Session | None = None) -> list[ManagerLine]:
    """The desk first, then its own trades, then strategies and scripts by key."""
    statement = select(ManagerLineRow)
    if session is not None:
        found = [_line(row) for row in session.scalars(statement).all()]
    else:
        with Session(get_engine()) as own:
            found = [_line(row) for row in own.scalars(statement).all()]
    return sorted(found, key=lambda line: line_order(line.key))


def find_line(session: Session, key: LineKey) -> ManagerLine | None:
    row = session.get(ManagerLineRow, str(key))
    return _line(row) if row else None


def put_line(session: Session, line: ManagerLine) -> None:
    row = session.get(ManagerLineRow, str(line.key))
    if row is None:
        row = ManagerLineRow(key=str(line.key))
        session.add(row)
    row.capital = line.capital
    row.stop = line.stop
    row.reason = line.reason
    row.set_by = line.set_by.value
    row.manager_capital = line.manager_capital
    row.manager_stop = line.manager_stop
    row.set_at = line.set_at.astimezone(UTC).replace(tzinfo=None)
    row.triggered_by = line.triggered_by


def _state(row: ManagerStateRow | None) -> ManagerState:
    if row is None:
        return OFF
    plan = None
    if row.plan_day is not None and row.plan_text is not None and row.plan_at is not None:
        plan = ManagerPlan(
            day=row.plan_day,
            text=row.plan_text,
            lesson_ids=tuple(json.loads(row.plan_lessons or "[]")),
            at=row.plan_at.replace(tzinfo=UTC),
        )
    return ManagerState(
        enabled=row.enabled,
        wakes_per_day=row.wakes_per_day or DEFAULT_WAKES_PER_DAY,
        next_wake_at=_aware(row.next_wake_at),
        next_wake_reason=row.next_wake_reason,
        last_wake_at=_aware(row.last_wake_at),
        last_audit_id=row.last_audit_id or 0,
        crossed=frozenset(json.loads(row.crossed or "[]")),
        closed_on=row.closed_on,
        stalled=row.stalled,
        plan=plan,
        updated_at=_aware(row.updated_at),
    )


def _line(row: ManagerLineRow) -> ManagerLine:
    return ManagerLine(
        key=parse_key(row.key),
        capital=row.capital,
        stop=row.stop,
        reason=row.reason,
        set_by=SetBy(row.set_by),
        manager_capital=row.manager_capital,
        manager_stop=row.manager_stop,
        set_at=row.set_at.replace(tzinfo=UTC),
        triggered_by=row.triggered_by,
    )


def _aware(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=UTC) if moment else None


def _naive(moment: datetime | None) -> datetime | None:
    return moment.astimezone(UTC).replace(tzinfo=None) if moment else None
