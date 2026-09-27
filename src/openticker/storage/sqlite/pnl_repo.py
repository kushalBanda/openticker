"""The paper account's P&L by day and by minute, and its fills grouped by
day and month (ADR 34 in docs/adr)."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from openticker.core.pnl import DayFill, DayPnl, IntradayPoint
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import DailyPnlRow, IntradayPnlRow, SandboxTradeRow


def upsert_day(day: DayPnl, now: datetime) -> None:
    """Recording a day again replaces it: a restart after the close re-runs it."""
    values = {
        "trading_date": day.trading_date,
        "realized_pnl": day.realized_pnl,
        "charges": day.charges,
        "unrealized_pnl": day.unrealized_pnl,
        "net_pnl": day.net_pnl,
        "open_value": day.open_value,
        "fills": day.fills,
        "complete": day.complete,
        "estimated": day.estimated,
        "recorded_at": now.astimezone(UTC).replace(tzinfo=None),
    }
    statement = insert(DailyPnlRow).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["trading_date"],
        set_={key: value for key, value in values.items() if key != "trading_date"},
    )
    with Session(get_engine()) as session:
        session.execute(statement)
        session.commit()


def day_recorded(trading_date: date) -> bool:
    with Session(get_engine()) as session:
        return session.get(DailyPnlRow, trading_date) is not None


def days_between(start: date, end: date) -> list[DayPnl]:
    """Oldest first, both ends included."""
    statement = (
        select(DailyPnlRow)
        .where(DailyPnlRow.trading_date >= start, DailyPnlRow.trading_date <= end)
        .order_by(DailyPnlRow.trading_date)
    )
    with Session(get_engine()) as session:
        return [_day(row) for row in session.scalars(statement)]


def last_day_before(trading_date: date) -> DayPnl | None:
    statement = (
        select(DailyPnlRow)
        .where(DailyPnlRow.trading_date < trading_date)
        .order_by(DailyPnlRow.trading_date.desc())
        .limit(1)
    )
    with Session(get_engine()) as session:
        row = session.scalars(statement).first()
        return _day(row) if row else None


def upsert_point(trading_date: date, point: IntradayPoint) -> None:
    values = {
        "trading_date": trading_date,
        "minute": point.minute.strftime("%H:%M"),
        "net_pnl": point.net_pnl,
        "realized_pnl": point.realized_pnl,
        "charges": point.charges,
        "unrealized_pnl": point.unrealized_pnl,
    }
    statement = insert(IntradayPnlRow).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["trading_date", "minute"],
        set_={key: value for key, value in values.items() if key not in ("trading_date", "minute")},
    )
    with Session(get_engine()) as session:
        session.execute(statement)
        session.commit()


def points_on(trading_date: date) -> list[IntradayPoint]:
    statement = (
        select(IntradayPnlRow)
        .where(IntradayPnlRow.trading_date == trading_date)
        .order_by(IntradayPnlRow.minute)
    )
    with Session(get_engine()) as session:
        return [
            IntradayPoint(
                minute=time.fromisoformat(row.minute),
                net_pnl=row.net_pnl,
                realized_pnl=row.realized_pnl,
                charges=row.charges,
                unrealized_pnl=row.unrealized_pnl,
            )
            for row in session.scalars(statement)
        ]


def prune_points(before: date) -> int:
    with Session(get_engine()) as session:
        result = session.execute(delete(IntradayPnlRow).where(IntradayPnlRow.trading_date < before))
        session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def delete_all(session: Session) -> None:
    """Both tables, inside the paper account's reset (ADR 37)."""
    session.execute(delete(DailyPnlRow))
    session.execute(delete(IntradayPnlRow))


@dataclass(frozen=True)
class FillCharges:
    filled_at: datetime  # tz-aware UTC
    charges: float | None
    detail: dict[str, float] | None  # each charge; None before it was recorded


def fills_between(start: datetime, end: datetime) -> list[DayFill]:
    """Every fill from `start` up to `end`, as the day's figures need them."""
    with Session(get_engine()) as session:
        rows = session.execute(
            select(SandboxTradeRow.realized_pnl, SandboxTradeRow.charges).where(
                SandboxTradeRow.filled_at >= _naive(start), SandboxTradeRow.filled_at < _naive(end)
            )
        ).all()
    return [DayFill(realized, charges) for realized, charges in rows]


def charges_between(start: datetime, end: datetime) -> list[FillCharges]:
    with Session(get_engine()) as session:
        rows = session.execute(
            select(
                SandboxTradeRow.filled_at, SandboxTradeRow.charges, SandboxTradeRow.charges_detail
            )
            .where(
                SandboxTradeRow.filled_at >= _naive(start), SandboxTradeRow.filled_at < _naive(end)
            )
            .order_by(SandboxTradeRow.filled_at)
        ).all()
    return [
        FillCharges(filled_at.replace(tzinfo=UTC), charges, json.loads(detail) if detail else None)
        for filled_at, charges, detail in rows
    ]


def first_fill_at() -> datetime | None:
    with Session(get_engine()) as session:
        first = session.scalar(
            select(SandboxTradeRow.filled_at).order_by(SandboxTradeRow.filled_at).limit(1)
        )
    return first.replace(tzinfo=UTC) if first else None


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)


def _day(row: DailyPnlRow) -> DayPnl:
    return DayPnl(
        trading_date=row.trading_date,
        realized_pnl=row.realized_pnl,
        charges=row.charges,
        unrealized_pnl=row.unrealized_pnl,
        net_pnl=row.net_pnl,
        open_value=row.open_value,
        fills=row.fills,
        complete=row.complete,
        estimated=row.estimated,
    )
