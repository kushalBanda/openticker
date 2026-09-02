from dataclasses import dataclass
from datetime import datetime

from strategy.core.constants import ORDER_STATUS_PENDING


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str
    quantity: int
    order_type: str
    placed_at_ts: datetime


@dataclass(frozen=True)
class Fill:
    order: Order
    fill_price: float
    fill_ts: datetime
    commission: float


@dataclass(frozen=True)
class OrderState:
    order: Order
    status: str = ORDER_STATUS_PENDING
