"""Domain events: facts that happened, published by use cases and consumed by
subscribers the use cases know nothing about (ADR 10 in docs/adr)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class OrderPlaced:
    order_id: str
    symbol: str
    side: str
    quantity: int
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class OrderFilled:
    order_id: str
    symbol: str
    side: str
    quantity: int
    price: float
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class OrderFailed:
    symbol: str
    reason: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class OrderModified:
    """A pending order's quantity, price or trigger changed. Audited, not notified."""

    order_id: str
    symbol: str
    change: str  # "price 950.0 -> 960.0, quantity 10 -> 20"
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class OrderCancelled:
    """A pending order withdrawn by the user, or expired at the session's end."""

    order_id: str
    symbol: str
    reason: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class RiskBreached:
    symbol: str
    reason: str
    detail: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class InstrumentSyncCompleted:
    broker: str
    count: int
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class BrokerSessionExpired:
    """The broker refused the stored session: live prices have stopped until
    the user logs in again."""

    broker: str
    detail: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class PositionSettled:
    """An expired futures or options position closed at its settlement price."""

    symbol: str
    product: str
    quantity: int  # signed, as held before settlement
    price: float
    realized_pnl: float
    detail: str  # how the price was reached
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class StrategyStarted:
    strategy_id: str
    run_id: str
    name: str
    legs: str  # what it entered, e.g. "SELL 75 NIFTY29SEP2623350CE @ 160.05, ..."
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class StrategyLegClosed:
    strategy_id: str
    run_id: str
    leg_id: str
    symbol: str
    reason: str
    detail: str
    realized_pnl: float
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class StrategyStopped:
    """A run ended: every leg it opened is closed, or could not be."""

    strategy_id: str
    run_id: str
    name: str
    reason: str
    detail: str
    realized_pnl: float
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ScriptStarted:
    script_id: str
    run_id: str
    name: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ScriptExited:
    """A hosted script's process ended, whatever the reason (ADR 25)."""

    script_id: str
    run_id: str
    name: str
    reason: str
    detail: str
    occurred_at: datetime = field(default_factory=_now)
