"""Withdraw every pending sandbox order (ADR 11 in docs/adr), a strategy's
included; the strategy itself is not stopped."""

from openticker.core.orders.models import Order, OrderResult
from openticker.events.bus import EventPublisher
from openticker.ports.sandbox_port import OrderSandbox
from openticker.use_cases.cancel_order import cancel_order


def cancel_all_orders(
    sandbox: OrderSandbox, events: EventPublisher, triggered_by: str
) -> list[tuple[Order, OrderResult]]:
    """One result per order that was pending; one that filled meanwhile says so."""
    return [
        (order, cancel_order(order.order_id, sandbox, events, triggered_by))
        for order in sandbox.pending_orders()
    ]
