"""Strategy commands, runs, their orders and timelines (ADR 21 in docs/adr).

Functions taking a `Session` run inside the caller's
`strategies_repo.write_transaction()`, so a check and the write it guards
happen under one lock.
"""

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from openticker.core.risk.models import PositionRisk, StrategyStopReason, TrailingStop, TrailMode
from openticker.core.strategies.runs import (
    Command,
    CommandKind,
    CommandStatus,
    LegStatus,
    Run,
    RunLeg,
    RunStatus,
)
from openticker.core.strategies.signals import SignalAction
from openticker.ports.models import Exchange, Product, Side
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import (
    StrategyCommandRow,
    StrategyEventRow,
    StrategyOrderRow,
    StrategyRunRow,
)
from openticker.storage.sqlite.strategies_repo import write_transaction

SCHEDULE_TRIGGER = "schedule"  # who sends a scheduled start
WEBHOOK_TRIGGER = "webhook"  # who sends a signal, and opens a signal run


@dataclass(frozen=True)
class RunOrder:
    id: str
    run_id: str
    leg_id: str
    intent: str  # entry, exit
    symbol: str
    exchange: str
    side: Side
    quantity: int
    # pending until the sandbox answers, then its order status; not_sent if it
    # never reached the sandbox
    status: str
    sandbox_order_id: str | None
    fill_price: float | None
    reason: str | None
    created_at: datetime  # tz-aware UTC


@dataclass(frozen=True)
class RunEvent:
    occurred_at: datetime  # tz-aware UTC
    message: str


# Commands


def add_command(
    session: Session,
    strategy_id: str,
    kind: CommandKind,
    triggered_by: str,
    now: datetime,
    broker: str | None = None,
    leg_id: str | None = None,
    action: SignalAction | None = None,
) -> Command:
    row = StrategyCommandRow(
        strategy_id=strategy_id,
        kind=kind.value,
        leg_id=leg_id,
        broker=broker,
        action=action.value if action else None,
        triggered_by=triggered_by,
        status=CommandStatus.PENDING.value,
        outcome=None,
        created_at=_naive(now),
        processed_at=None,
    )
    session.add(row)
    session.flush()
    return _command(row)


def pending_commands_of(session: Session, strategy_id: str) -> list[Command]:
    statement = (
        select(StrategyCommandRow)
        .where(
            StrategyCommandRow.strategy_id == strategy_id,
            StrategyCommandRow.status == CommandStatus.PENDING.value,
        )
        .order_by(StrategyCommandRow.id)
    )
    return [_command(row) for row in session.scalars(statement).all()]


def scheduled_start_since(session: Session, strategy_id: str, since: datetime) -> bool:
    """Whether the schedule already sent a start at or after `since`."""
    statement = select(StrategyCommandRow.id).where(
        StrategyCommandRow.strategy_id == strategy_id,
        StrategyCommandRow.kind == CommandKind.START.value,
        StrategyCommandRow.triggered_by == SCHEDULE_TRIGGER,
        StrategyCommandRow.created_at >= _naive(since),
    )
    return session.scalars(statement).first() is not None


def settle_command(
    session: Session, command_id: int, status: CommandStatus, outcome: str, now: datetime
) -> None:
    row = session.get(StrategyCommandRow, command_id)
    if row is not None and row.status == CommandStatus.PENDING.value:
        row.status = status.value
        row.outcome = outcome
        row.processed_at = _naive(now)


def next_pending_command() -> Command | None:
    """The oldest command not yet carried out."""
    statement = (
        select(StrategyCommandRow)
        .where(StrategyCommandRow.status == CommandStatus.PENDING.value)
        .order_by(StrategyCommandRow.id)
        .limit(1)
    )
    with Session(get_engine()) as session:
        row = session.scalars(statement).first()
        return _command(row) if row else None


def commands_by_id(ids: list[int]) -> dict[int, Command]:
    statement = select(StrategyCommandRow).where(StrategyCommandRow.id.in_(ids))
    with Session(get_engine()) as session:
        return {row.id: _command(row) for row in session.scalars(statement).all()}


def recent_commands(strategy_id: str, limit: int) -> list[Command]:
    """Newest first."""
    statement = (
        select(StrategyCommandRow)
        .where(StrategyCommandRow.strategy_id == strategy_id)
        .order_by(StrategyCommandRow.id.desc())
        .limit(limit)
    )
    with Session(get_engine()) as session:
        return [_command(row) for row in session.scalars(statement).all()]


# Runs


def active_run_of(session: Session, strategy_id: str) -> Run | None:
    statement = select(StrategyRunRow).where(
        StrategyRunRow.strategy_id == strategy_id,
        StrategyRunRow.status != RunStatus.ENDED.value,
    )
    row = session.scalars(statement).first()
    return _run(row) if row else None


def find_active_run(strategy_id: str) -> Run | None:
    with Session(get_engine()) as session:
        return active_run_of(session, strategy_id)


def insert_run(session: Session, run: Run) -> None:
    session.add(StrategyRunRow(id=run.id, **_run_fields(run)))


def update_run(session: Session, run: Run) -> None:
    row = session.get(StrategyRunRow, run.id)
    if row is None:
        raise LookupError(f"no strategy run {run.id}")
    for name, value in _run_fields(run).items():
        setattr(row, name, value)


def new_run_id() -> str:
    return "run_" + secrets.token_hex(6)


def save_run(run: Run) -> None:
    with write_transaction() as session:
        update_run(session, run)


def find_run(run_id: str) -> Run | None:
    with Session(get_engine()) as session:
        row = session.get(StrategyRunRow, run_id)
        return _run(row) if row else None


def active_runs() -> list[Run]:
    statement = (
        select(StrategyRunRow)
        .where(StrategyRunRow.status != RunStatus.ENDED.value)
        .order_by(StrategyRunRow.started_at)
    )
    with Session(get_engine()) as session:
        return [_run(row) for row in session.scalars(statement).all()]


def list_runs(strategy_id: str, limit: int) -> list[Run]:
    """Newest first."""
    statement = (
        select(StrategyRunRow)
        .where(StrategyRunRow.strategy_id == strategy_id)
        .order_by(StrategyRunRow.started_at.desc())
        .limit(limit)
    )
    with Session(get_engine()) as session:
        return [_run(row) for row in session.scalars(statement).all()]


def realized_since(strategy_id: str, since: datetime, excluding: str) -> float:
    """Realized P&L of the strategy's other runs started at or after `since`."""
    statement = select(func.coalesce(func.sum(StrategyRunRow.realized_pnl), 0.0)).where(
        StrategyRunRow.strategy_id == strategy_id,
        StrategyRunRow.started_at >= _naive(since),
        StrategyRunRow.id != excluding,
    )
    with Session(get_engine()) as session:
        return float(session.scalar(statement) or 0.0)


# Orders


def add_order(
    run_id: str,
    leg: RunLeg,
    intent: str,
    side: Side,
    quantity: int,
    now: datetime,
) -> str:
    order_id = "so_" + secrets.token_hex(6)
    with write_transaction() as session:
        session.add(
            StrategyOrderRow(
                id=order_id,
                run_id=run_id,
                leg_id=leg.leg_id,
                intent=intent,
                symbol=leg.symbol,
                exchange=leg.exchange.value,
                side=side.value,
                quantity=quantity,
                status="pending",
                sandbox_order_id=None,
                fill_price=None,
                reason=None,
                created_at=_naive(now),
                updated_at=None,
            )
        )
    return order_id


def settle_order(
    order_id: str,
    status: str,
    sandbox_order_id: str | None,
    fill_price: float | None,
    reason: str | None,
    now: datetime,
) -> None:
    with write_transaction() as session:
        row = session.get(StrategyOrderRow, order_id)
        if row is None:
            raise LookupError(f"no strategy order {order_id}")
        row.status = status
        row.sandbox_order_id = sandbox_order_id
        row.fill_price = fill_price
        row.reason = reason
        row.updated_at = _naive(now)


def list_orders(run_id: str) -> list[RunOrder]:
    statement = (
        select(StrategyOrderRow)
        .where(StrategyOrderRow.run_id == run_id)
        .order_by(literal_column("rowid"))  # the order they were written in
    )
    with Session(get_engine()) as session:
        return [
            RunOrder(
                id=row.id,
                run_id=row.run_id,
                leg_id=row.leg_id,
                intent=row.intent,
                symbol=row.symbol,
                exchange=row.exchange,
                side=Side(row.side),
                quantity=row.quantity,
                status=row.status,
                sandbox_order_id=row.sandbox_order_id,
                fill_price=row.fill_price,
                reason=row.reason,
                created_at=row.created_at.replace(tzinfo=UTC),
            )
            for row in session.scalars(statement).all()
        ]


# Timeline


def add_event(run_id: str, now: datetime, message: str) -> None:
    with write_transaction() as session:
        session.add(StrategyEventRow(run_id=run_id, occurred_at=_naive(now), message=message))


def list_events(run_id: str, limit: int) -> list[RunEvent]:
    """The latest `limit`, oldest first."""
    statement = (
        select(StrategyEventRow)
        .where(StrategyEventRow.run_id == run_id)
        .order_by(StrategyEventRow.id.desc())
        .limit(limit)
    )
    with Session(get_engine()) as session:
        rows = session.scalars(statement).all()
    return [RunEvent(row.occurred_at.replace(tzinfo=UTC), row.message) for row in reversed(rows)]


def _command(row: StrategyCommandRow) -> Command:
    return Command(
        id=row.id,
        strategy_id=row.strategy_id,
        kind=CommandKind(row.kind),
        triggered_by=row.triggered_by,
        status=CommandStatus(row.status),
        created_at=row.created_at.replace(tzinfo=UTC),
        leg_id=row.leg_id,
        broker=row.broker,
        action=SignalAction(row.action) if row.action else None,
        outcome=row.outcome,
        processed_at=row.processed_at.replace(tzinfo=UTC) if row.processed_at else None,
    )


def _run_fields(run: Run) -> dict[str, Any]:
    return {
        "strategy_id": run.strategy_id,
        "broker": run.broker,
        "product": run.product.value,
        "status": run.status.value,
        "trigger": run.trigger,
        "started_at": _naive(run.started_at),
        "ended_at": _naive(run.ended_at) if run.ended_at else None,
        "stop_reason": run.stop_reason.value if run.stop_reason else None,
        "stop_detail": run.stop_detail,
        "legs": json.dumps([_encode_leg(leg) for leg in run.legs]),
        "peak_mtm": run.peak_mtm,
        "trough_mtm": run.trough_mtm,
        "lock_floor": run.lock_floor,
        "stops_at_entry": run.stops_at_entry,
        "realized_pnl": run.realized_pnl,
    }


def _run(row: StrategyRunRow) -> Run:
    return Run(
        id=row.id,
        strategy_id=row.strategy_id,
        broker=row.broker,
        product=Product(row.product),
        status=RunStatus(row.status),
        trigger=row.trigger,
        started_at=row.started_at.replace(tzinfo=UTC),
        legs=tuple(_decode_leg(leg) for leg in json.loads(row.legs)),
        peak_mtm=row.peak_mtm,
        trough_mtm=row.trough_mtm or 0.0,
        lock_floor=row.lock_floor,
        stops_at_entry=row.stops_at_entry,
        stop_reason=StrategyStopReason(row.stop_reason) if row.stop_reason else None,
        stop_detail=row.stop_detail,
        ended_at=row.ended_at.replace(tzinfo=UTC) if row.ended_at else None,
    )


def _encode_leg(leg: RunLeg) -> dict[str, Any]:
    risk = leg.risk
    return {
        "leg_id": leg.leg_id,
        "symbol": leg.symbol,
        "exchange": leg.exchange.value,
        "side": leg.side.value,
        "quantity": leg.quantity,
        "status": leg.status.value,
        "entry_price": leg.entry_price,
        "entered_at": _encode_moment(leg.entered_at),
        "exit_price": leg.exit_price,
        "exit_reason": leg.exit_reason,
        "retry_at": _encode_moment(leg.retry_at),
        "failed_exits": leg.failed_exits,
        "spec_leg": leg.spec_leg,
        "risk": None
        if risk is None
        else {
            "initial_sl": risk.initial_sl,
            "current_sl": risk.current_sl,
            "target": risk.target,
            "highest_price": risk.highest_price,
            "lowest_price": risk.lowest_price,
            "trailing_step": risk.trailing.step if risk.trailing else None,
        },
    }


def _decode_leg(data: dict[str, Any]) -> RunLeg:
    side = Side(data["side"])
    risk = data["risk"]
    return RunLeg(
        leg_id=data["leg_id"],
        symbol=data["symbol"],
        exchange=Exchange(data["exchange"]),
        side=side,
        quantity=data["quantity"],
        status=LegStatus(data["status"]),
        entry_price=data["entry_price"],
        entered_at=_decode_moment(data["entered_at"]),
        exit_price=data["exit_price"],
        exit_reason=data["exit_reason"],
        retry_at=_decode_moment(data["retry_at"]),
        failed_exits=data["failed_exits"],
        spec_leg=data.get("spec_leg"),
        risk=None
        if risk is None
        else PositionRisk(
            side=side,
            entry_price=data["entry_price"],
            quantity=data["quantity"],
            initial_sl=risk["initial_sl"],
            current_sl=risk["current_sl"],
            target=risk["target"],
            highest_price=risk["highest_price"],
            lowest_price=risk["lowest_price"],
            capital_cap=None,
            trailing=None
            if risk["trailing_step"] is None
            else TrailingStop(mode=TrailMode.CONTINUOUS, step=risk["trailing_step"], trigger=0.0),
        ),
    )


def _encode_moment(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat()


def _decode_moment(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)
