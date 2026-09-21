from dataclasses import dataclass
from enum import StrEnum

from openticker.ports.models import Instrument, Side


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    PLACED = "PLACED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class OrderRequest:
    instrument: Instrument
    side: Side
    quantity: int
    order_type: str  # MARKET / LIMIT / SL / SL-M
    price: float | None
    triggered_by: str  # "mcp" | "rest" | "webhook:chartink" — audit trail, not behavior branching


@dataclass(frozen=True)
class OrderResult:
    status: OrderStatus
    broker_order_id: str | None
    reason: str | None


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str | None
