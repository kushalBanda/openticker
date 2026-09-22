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
