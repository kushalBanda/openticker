"""Recent orders from the order adapter, most recent first."""

from openticker.core.orders.models import Order
from openticker.ports.broker_port import BrokerPort


def get_orderbook(broker: BrokerPort, limit: int) -> list[Order]:
    return broker.get_orderbook(limit)
