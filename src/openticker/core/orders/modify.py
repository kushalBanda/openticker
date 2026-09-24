"""What a change to a resting order may touch (ADR 11 in docs/adr): its
quantity, limit price and trigger price. Order type, instrument, side and
product stay as placed; changing those is a cancel and a new order."""

from openticker.core.orders.models import (
    Order,
    OrderChanges,
    OrderRequest,
    OrderStatus,
    OrderType,
)


class ChangeRefused(ValueError):
    """The change can't apply to this order; the message says why."""


def apply_changes(order: Order, changes: OrderChanges) -> OrderRequest:
    """The order as it would be after the change. Whether the result is well
    formed (lot, tick, an SL's limit against its trigger) is validate_order's
    question."""
    if order.status is not OrderStatus.PENDING:
        raise ChangeRefused(f"order {order.order_id} is {order.status}; only PENDING can change")
    if changes.price is not None and order.order_type not in (OrderType.LIMIT, OrderType.SL):
        raise ChangeRefused(f"{order.order_type} orders take no price")
    if changes.trigger_price is not None and order.order_type not in (OrderType.SL, OrderType.SL_M):
        raise ChangeRefused(f"{order.order_type} orders take no trigger_price")
    request = OrderRequest(
        instrument=order.instrument,
        side=order.side,
        quantity=changes.quantity if changes.quantity is not None else order.quantity,
        product=order.product,
        order_type=order.order_type,
        price=changes.price if changes.price is not None else order.price,
        triggered_by=order.triggered_by,
        strategy_id=order.strategy_id,
        run_id=order.run_id,
        trigger_price=(
            changes.trigger_price if changes.trigger_price is not None else order.trigger_price
        ),
    )
    if not describe_change(order, request):
        raise ChangeRefused(
            "nothing to change: give a new quantity, price or trigger_price that differs "
            "from the order's"
        )
    return request


def describe_change(order: Order, request: OrderRequest) -> str:
    """'price 950.0 -> 960.0, quantity 10 -> 20': the fields that differ."""
    pairs = (
        ("quantity", order.quantity, request.quantity),
        ("price", order.price, request.price),
        ("trigger_price", order.trigger_price, request.trigger_price),
    )
    return ", ".join(f"{name} {old} -> {new}" for name, old, new in pairs if old != new)
