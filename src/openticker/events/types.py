"""Domain events: facts that happened, published by use cases and consumed by
subscribers the use cases know nothing about (ADR 10 in docs/adr)."""

from dataclasses import dataclass, field, is_dataclass
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
class BrokerConnected:
    """A broker session was stored: the user logged in to the broker (ADR 33)."""

    broker: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class BrokerDisconnected:
    """The stored broker session was deleted by the user (ADR 33)."""

    broker: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class PaperAccountReset:
    """Every paper order, trade and position was deleted and the funds put
    back to the starting capital (ADR 37). Counts are what was deleted."""

    capital: float
    orders: int
    trades: int
    positions: int
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class WatchlistChanged:
    """A watchlist was created, renamed or deleted, or instruments were added
    to or removed from it (ADR 36). Audited, so the web app hears of an
    agent's change as it does of any other."""

    watchlist_id: str
    name: str
    change: str  # created, renamed, deleted, added, removed
    triggered_by: str
    symbols: tuple[str, ...] = ()  # added or removed, as OpenTicker names them
    previous_name: str | None = None  # renamed only
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


@dataclass(frozen=True)
class ChargeRatesDiffer:
    """The broker's contract note charged a sample order differently from the
    rates the sandbox charges: the rates file needs updating (ADR 28)."""

    broker: str
    rates_as_of: str  # the rates file's date
    differing: int  # samples that differ
    checked: int  # samples the broker priced
    detail: str  # each differing figure, ours and the broker's
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ChargeRatesChecked:
    """A charge-rate check ran, whatever it found: when the rates were last
    checked against the broker (ADR 28). Audited, not notified."""

    broker: str
    rates_as_of: str  # the rates file's date
    differing: int
    checked: int
    skipped: int  # segments with no sample priced
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class AgentJobStarted:
    """The daemon started the user's coding agent on a job (ADR 29). Audited."""

    job_id: str
    kind: str
    strategy_id: str
    harness: str
    triggered_by: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class AgentJobEnded:
    """An agent job ended, whatever the reason; a review's summary starts
    with its verdict."""

    job_id: str
    kind: str
    strategy_id: str
    strategy_name: str
    reason: str
    detail: str
    summary: str | None
    cost_usd: float | None
    occurred_at: datetime = field(default_factory=_now)


# Every event's name, as the audit log records it.
EVENT_TYPE_NAMES = tuple(
    name
    for name, value in list(globals().items())
    if isinstance(value, type) and is_dataclass(value)
)
