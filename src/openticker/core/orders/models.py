"""Order shapes shared by every entry point (MCP, REST, strategies) and every
order adapter. Only the sandbox places orders (ADR 6 and ADR 11 in docs/adr)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from openticker.ports.models import Instrument, Product, Side


class OrderStatus(StrEnum):
    PENDING = "PENDING"  # resting until the price crosses it
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"  # by the user, or expired at the session's end


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


@dataclass(frozen=True)
class OrderRequest:
    instrument: Instrument
    side: Side
    quantity: int
    product: Product
    order_type: OrderType
    price: float | None  # limit price: LIMIT and SL only
    triggered_by: str  # "mcp", "rest", "strategy:<id>": audit trail, never branched on
    strategy_id: str | None = None
    run_id: str | None = None
    trigger_price: float | None = None  # SL and SL-M only


@dataclass(frozen=True)
class OrderResult:
    status: OrderStatus
    broker_order_id: str | None
    reason: str | None
    fill_price: float | None = None


@dataclass(frozen=True)
class Order:
    """One row of the order book."""

    order_id: str
    instrument: Instrument
    side: Side
    quantity: int
    product: Product
    order_type: OrderType
    status: OrderStatus
    fill_price: float | None
    reason: str | None
    triggered_by: str
    placed_at: datetime  # tz-aware UTC
    strategy_id: str | None
    run_id: str | None
    price: float | None = None
    trigger_price: float | None = None
    triggered: bool = False  # an SL order whose trigger has been crossed: now a resting limit


@dataclass(frozen=True)
class Trade:
    """One fill."""

    order_id: str
    instrument: Instrument
    side: Side
    quantity: int
    price: float
    product: Product
    filled_at: datetime  # tz-aware UTC
    triggered_by: str
    strategy_id: str | None
    run_id: str | None
    charges: float | None = None  # None: filled before costs were modelled (ADR 28)
    expected_price: float | None = None  # what the order was placed against
    realized_pnl: float | None = None  # what this fill closed, before charges; None: not recorded
    charges_detail: Mapping[str, float] | None = None  # each charge, and "gst"; None: not recorded


@dataclass(frozen=True)
class OrderChanges:
    """A change to a resting order; None keeps the current value."""

    quantity: int | None = None
    price: float | None = None
    trigger_price: float | None = None


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str | None
