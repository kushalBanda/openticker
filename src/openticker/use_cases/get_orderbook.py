"""Recent orders from the order adapter, most recent first."""

from datetime import datetime

from openticker.core.orders.models import Order
from openticker.ports.broker_port import BrokerPort


def get_orderbook(broker: BrokerPort, limit: int, since: datetime | None = None) -> list[Order]:
    """The newest `limit` orders; with `since`, only those placed at or after it."""
    orders = broker.get_orderbook(limit)
    return orders if since is None else [o for o in orders if o.placed_at >= since]
