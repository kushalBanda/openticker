"""Order shapes shared by every entry point (MCP, REST, strategies) and every
order adapter. Only the sandbox places orders (ADR 6 and ADR 11 in docs/adr)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from openticker.ports.models import Instrument, Product, Side


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


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
    price: float | None  # limit price; None for MARKET
    triggered_by: str  # "mcp", "rest", "strategy:<id>": audit trail, never branched on
    strategy_id: str | None = None
    run_id: str | None = None


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


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str | None
