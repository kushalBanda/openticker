"""Withdraw a pending order (ADR 11 in docs/adr)."""

from openticker.core.orders.models import OrderResult, OrderStatus
from openticker.events.bus import EventPublisher
from openticker.events.types import OrderCancelled
from openticker.ports.broker_port import BrokerPort
from openticker.use_cases.errors import UnknownOrderError


def cancel_order(
    order_id: str, broker: BrokerPort, events: EventPublisher, triggered_by: str
) -> OrderResult:
    """A result whose status isn't CANCELLED says why nothing changed: the
    order had already filled or been cancelled."""
    order = broker.get_order(order_id)
    if order is None:
        raise UnknownOrderError(f"no order {order_id!r}; get_orderbook lists them")
    result = broker.cancel_order(order_id)
    if result.status is OrderStatus.CANCELLED:
        events.publish(
            OrderCancelled(
                order_id=order_id,
                symbol=order.instrument.symbol,
                reason=result.reason or "cancelled",
                triggered_by=triggered_by,
            )
        )
    return result
