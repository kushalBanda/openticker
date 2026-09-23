"""A strategy run: the contracts it entered, each leg's state and ratchets,
and the P&L arithmetic over them. Pure. Rules: ADR 21 in docs/adr."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from openticker.core.risk.models import (
    PositionRisk,
    StrategyStopReason,
    TrailingStop,
    TrailMode,
    as_price,
)
from openticker.core.strategies.models import Horizon, LegSpec, RiskValue, SignalLeg
from openticker.core.strategies.signals import SignalAction
from openticker.ports.models import Exchange, Product, Side


class CommandKind(StrEnum):
    START = "start"
    STOP = "stop"
    KILL = "kill"
    CLOSE_LEG = "close_leg"
    SIGNAL = "signal"  # an alert for a signal strategy (ADR 24)


class CommandStatus(StrEnum):
    PENDING = "pending"  # waiting for the daemon's runner
    DONE = "done"
    REFUSED = "refused"  # `outcome` says why


@dataclass(frozen=True)
class Command:
    id: int
    strategy_id: str
    kind: CommandKind
    triggered_by: str
    status: CommandStatus
    created_at: datetime  # tz-aware UTC
    leg_id: str | None = None
    broker: str | None = None
    action: SignalAction | None = None  # signal only
    outcome: str | None = None
    processed_at: datetime | None = None


class RunStatus(StrEnum):
    OPEN = "open"  # entering, or holding legs under watch
    STOPPING = "stopping"  # a stop was decided; closing whatever is still open
    ENDED = "ended"


class LegStatus(StrEnum):
    PENDING = "pending"  # entry not placed yet
    OPEN = "open"
    CLOSING = "closing"  # exit decided; its order has not filled yet
    CLOSED = "closed"
    FAILED = "failed"  # the entry never filled


@dataclass(frozen=True)
class RunLeg:
    leg_id: str
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int  # units
    status: LegStatus
    entry_price: float | None = None
    entered_at: datetime | None = None  # tz-aware UTC
    exit_price: float | None = None
    exit_reason: str | None = None  # a BreachReason, "manual", or the run's stop reason
    risk: PositionRisk | None = None  # set while open; carries the ratchets
    retry_at: datetime | None = None  # a failed exit is tried again from then
    failed_exits: int = 0
    # A signal run's position: the defined leg it was entered for. An options
    # run's legs are the defined legs themselves.
    spec_leg: str | None = None

    @property
    def defined_as(self) -> str:
        return self.spec_leg or self.leg_id

    @property
    def is_open(self) -> bool:
        return self.status in (LegStatus.OPEN, LegStatus.CLOSING)

    @property
    def realized_pnl(self) -> float:
        if (
            self.status is not LegStatus.CLOSED
            or self.entry_price is None
            or self.exit_price is None
        ):
            return 0.0
        return leg_pnl(self.side, self.entry_price, self.exit_price, self.quantity)


@dataclass(frozen=True)
class Run:
    id: str
    strategy_id: str
    broker: str
    product: Product
    status: RunStatus
    trigger: str  # who started it: "mcp", "rest:<key>", "schedule"
    started_at: datetime  # tz-aware UTC
    legs: tuple[RunLeg, ...]
    peak_mtm: float = 0.0
    trough_mtm: float = 0.0
    lock_floor: float | None = None
    stops_at_entry: bool = False
    stop_reason: StrategyStopReason | None = None
    stop_detail: str | None = None
    ended_at: datetime | None = None

    @property
    def realized_pnl(self) -> float:
        return round(sum(leg.realized_pnl for leg in self.legs), 2)


def product_for(horizon: Horizon) -> Product:
    return Product.MIS if horizon is Horizon.INTRADAY else Product.NRML


def leg_pnl(side: Side, entry: float, exit: float, quantity: int) -> float:
    return (exit - entry if side is Side.BUY else entry - exit) * quantity


def leg_risk(
    leg: LegSpec | SignalLeg, side: Side, entry_price: float, quantity: int
) -> PositionRisk:
    """The leg's stop loss, target and trailing stop as prices, measured from
    where it actually filled on `side`. A stop that would sit at or below zero
    is left unset rather than moved."""
    long = side is Side.BUY
    stop = _away(entry_price, leg.stop_loss, -1 if long else 1)
    return PositionRisk(
        side=side,
        entry_price=entry_price,
        quantity=quantity,
        initial_sl=stop,
        current_sl=stop,
        target=_away(entry_price, leg.target, 1 if long else -1),
        highest_price=None,
        lowest_price=None,
        capital_cap=None,
        trailing=None
        if leg.trailing is None
        else TrailingStop(
            mode=TrailMode.CONTINUOUS, step=_distance(entry_price, leg.trailing), trigger=0.0
        ),
    )


def _away(entry: float, value: RiskValue | None, direction: int) -> float | None:
    if value is None:
        return None
    return as_price(round(entry + direction * _distance(entry, value), 2))


def _distance(entry: float, value: RiskValue) -> float:
    return entry * value.value / 100 if value.percent else value.value
