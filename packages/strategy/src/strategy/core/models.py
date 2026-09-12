from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from strategy.core.constants import ORDER_STATUS_PENDING


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str
    quantity: int
    order_type: str
    placed_at_ts: datetime
    # Client-generated identity, not a broker's order id. PaperBroker/
    # LiveBroker pair this with the broker's own id once accepted, so a
    # later poll or WebSocket update matches back to the order that caused
    # it - BacktestBroker never needs this, it has no async round-trip to
    # a real broker to reconcile against.
    order_id: str = field(default_factory=lambda: str(uuid4()))


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
    # Kite's own order id, set once the broker accepts the order (None
    # before that, and always None for BacktestBroker, which has no real
    # broker to assign one). Paired with Order.order_id so a later poll or
    # WebSocket update matches back to the order that caused it.
    broker_order_id: str | None = None
