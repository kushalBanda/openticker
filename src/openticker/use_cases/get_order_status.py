"""One order, whatever its status."""

from openticker.core.orders.models import Order
from openticker.ports.broker_port import BrokerPort
from openticker.use_cases.errors import UnknownOrderError


def get_order_status(broker: BrokerPort, order_id: str) -> Order:
    order = broker.get_order(order_id)
    if order is None:
        raise UnknownOrderError(f"no order {order_id!r}; get_orderbook lists them")
    return order
