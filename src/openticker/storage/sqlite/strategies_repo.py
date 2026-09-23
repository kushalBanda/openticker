"""Strategy definitions (ADR 20 in docs/adr), stored as versioned JSON."""

import json
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from openticker.core.risk.models import LockMode, ProfitLock, StrategyLimits
from openticker.core.strategies.models import (
    Horizon,
    LegSpec,
    OptionsStrategySpec,
    RelativeExpiry,
    RiskValue,
    Schedule,
    StrikeSelector,
)
from openticker.ports.models import Exchange, InstrumentType, Side
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import StrategyRow

DEFINITION_VERSION = 1
OPTIONS_KIND = "options"
SANDBOX_MODE = "sandbox"


class DuplicateStrategyNameError(Exception):
    pass


@dataclass(frozen=True)
class StoredStrategy:
    id: str
    name: str
    kind: str
    spec: OptionsStrategySpec
    mode: str
    locked: bool
    created_at: datetime  # tz-aware UTC
    updated_at: datetime  # tz-aware UTC
    scheduled_broker: str | None = None  # None: enters only on start_strategy


def insert_strategy(name: str, spec: OptionsStrategySpec, now: datetime) -> StoredStrategy:
    with write_transaction() as session:
        _refuse_taken(session, name)
        row = StrategyRow(
            id="stg_" + secrets.token_hex(6),
            name=name,
            kind=OPTIONS_KIND,
            definition=json.dumps(_encode(spec)),
            mode=SANDBOX_MODE,
            locked=False,
            created_at=_naive(now),
            updated_at=_naive(now),
            deleted_at=None,
            scheduled_broker=None,
        )
        session.add(row)
        session.flush()
        return _stored(row)


def update_strategy(
    strategy_id: str,
    name: str,
    spec: OptionsStrategySpec,
    now: datetime,
    guard: Callable[[Session], None] = lambda session: None,
) -> StoredStrategy | None:
    """None when no strategy has that id. `guard` runs inside the write lock
    before anything changes, and refuses by raising."""
    with write_transaction() as session:
        row = _live(session, strategy_id)
        if row is None:
            return None
        guard(session)
        if name != row.name:
            _refuse_taken(session, name)
        row.name = name
        row.definition = json.dumps(_encode(spec))
        row.updated_at = _naive(now)
        session.flush()
        return _stored(row)


def find_strategy(strategy_id: str) -> StoredStrategy | None:
    with Session(get_engine()) as session:
        return load_strategy(session, strategy_id)


def load_strategy(session: Session, strategy_id: str) -> StoredStrategy | None:
    """Inside a caller's transaction. None when deleted or never created."""
    row = _live(session, strategy_id)
    return _stored(row) if row else None


def set_locked(session: Session, strategy_id: str, locked: bool) -> None:
    row = _live(session, strategy_id)
    if row is not None:
        row.locked = locked


def set_scheduled(session: Session, strategy_id: str, broker: str | None) -> None:
    row = _live(session, strategy_id)
    if row is not None:
        row.scheduled_broker = broker


def list_scheduled() -> list[StoredStrategy]:
    statement = select(StrategyRow).where(
        StrategyRow.deleted_at.is_(None), StrategyRow.scheduled_broker.is_not(None)
    )
    with Session(get_engine()) as session:
        return [_stored(row) for row in session.scalars(statement).all()]


def list_strategies() -> list[StoredStrategy]:
    statement = (
        select(StrategyRow).where(StrategyRow.deleted_at.is_(None)).order_by(StrategyRow.name)
    )
    with Session(get_engine()) as session:
        return [_stored(row) for row in session.scalars(statement).all()]


def delete_strategy(
    strategy_id: str, now: datetime, guard: Callable[[Session], None] = lambda session: None
) -> bool:
    """False when no strategy has that id. The row stays, marked deleted."""
    with write_transaction() as session:
        row = _live(session, strategy_id)
        if row is None:
            return False
        guard(session)
        row.deleted_at = _naive(now)
        return True


@contextmanager
def write_transaction() -> Iterator[Session]:
    """A session holding SQLite's write lock from its first statement until
    commit: the strategy's checks and its changes happen under one lock, so
    the MCP server, the REST API and the daemon can't interleave them."""
    with Session(get_engine()) as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield session
        session.commit()


def _live(session: Session, strategy_id: str) -> StrategyRow | None:
    statement = select(StrategyRow).where(
        StrategyRow.id == strategy_id, StrategyRow.deleted_at.is_(None)
    )
    return session.scalars(statement).one_or_none()


def _refuse_taken(session: Session, name: str) -> None:
    statement = select(StrategyRow.id).where(
        StrategyRow.name == name, StrategyRow.deleted_at.is_(None)
    )
    if session.scalars(statement).first() is not None:
        raise DuplicateStrategyNameError(f"a strategy named {name!r} already exists")


def _stored(row: StrategyRow) -> StoredStrategy:
    return StoredStrategy(
        id=row.id,
        name=row.name,
        kind=row.kind,
        spec=_decode(json.loads(row.definition)),
        mode=row.mode,
        locked=row.locked,
        created_at=row.created_at.replace(tzinfo=UTC),
        updated_at=row.updated_at.replace(tzinfo=UTC),
        scheduled_broker=row.scheduled_broker,
    )


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)


def _encode(spec: OptionsStrategySpec) -> dict[str, Any]:
    schedule, limits = spec.schedule, spec.limits
    lock = limits.lock_profit
    return {
        "version": DEFINITION_VERSION,
        "underlying": spec.underlying,
        "exchange": spec.exchange.value,
        "horizon": spec.horizon.value,
        "legs": [
            {
                "side": leg.side.value,
                "lots": leg.lots,
                "option_type": leg.option_type.value,
                "expiry": leg.expiry.value,
                "strike": None
                if leg.strike is None
                else {"offset": leg.strike.offset, "fixed_strike": leg.strike.fixed_strike},
                "stop_loss": _encode_risk(leg.stop_loss),
                "target": _encode_risk(leg.target),
                "trailing": _encode_risk(leg.trailing),
            }
            for leg in spec.legs
        ],
        "schedule": {
            "entry_time": _encode_time(schedule.entry_time),
            "exit_time": _encode_time(schedule.exit_time),
            "weekdays": sorted(schedule.weekdays),
            "exit_on_expiry": schedule.exit_on_expiry,
        },
        "limits": {
            "combined_stop_loss": limits.combined_stop_loss,
            "combined_target": limits.combined_target,
            "lock_profit": None
            if lock is None
            else {
                "arm_at": lock.arm_at,
                "lock": lock.lock,
                "mode": lock.mode.value,
                "trail_step": lock.trail_step,
            },
            "stops_to_entry_on_leg_stop": limits.stops_to_entry_on_leg_stop,
            "daily_loss_limit": limits.daily_loss_limit,
        },
    }


def _decode(data: dict[str, Any]) -> OptionsStrategySpec:
    if data.get("version") != DEFINITION_VERSION:
        raise ValueError(f"unknown strategy definition version {data.get('version')!r}")
    schedule, limits = data["schedule"], data["limits"]
    lock = limits["lock_profit"]
    return OptionsStrategySpec(
        underlying=data["underlying"],
        exchange=Exchange(data["exchange"]),
        horizon=Horizon(data["horizon"]),
        legs=tuple(
            LegSpec(
                side=Side(leg["side"]),
                lots=leg["lots"],
                option_type=InstrumentType(leg["option_type"]),
                expiry=RelativeExpiry(leg["expiry"]),
                strike=None if leg["strike"] is None else StrikeSelector(**leg["strike"]),
                stop_loss=_decode_risk(leg["stop_loss"]),
                target=_decode_risk(leg["target"]),
                trailing=_decode_risk(leg["trailing"]),
            )
            for leg in data["legs"]
        ),
        schedule=Schedule(
            entry_time=_decode_time(schedule["entry_time"]),
            exit_time=_decode_time(schedule["exit_time"]),
            weekdays=frozenset(schedule["weekdays"]),
            exit_on_expiry=schedule["exit_on_expiry"],
        ),
        limits=StrategyLimits(
            combined_stop_loss=limits["combined_stop_loss"],
            combined_target=limits["combined_target"],
            lock_profit=None
            if lock is None
            else ProfitLock(
                arm_at=lock["arm_at"],
                lock=lock["lock"],
                mode=LockMode(lock["mode"]),
                trail_step=lock["trail_step"],
            ),
            stops_to_entry_on_leg_stop=limits["stops_to_entry_on_leg_stop"],
            daily_loss_limit=limits["daily_loss_limit"],
        ),
    )


def _encode_risk(value: RiskValue | None) -> dict[str, Any] | None:
    return None if value is None else {"value": value.value, "percent": value.percent}


def _decode_risk(data: dict[str, Any] | None) -> RiskValue | None:
    return None if data is None else RiskValue(value=data["value"], percent=data["percent"])


def _encode_time(at: time | None) -> str | None:
    return None if at is None else at.strftime("%H:%M")


def _decode_time(text: str | None) -> time | None:
    return None if text is None else time.fromisoformat(text)
