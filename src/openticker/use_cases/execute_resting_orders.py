"""The sandbox's execution engine, one pass (ADR 11 in docs/adr): expires
pending orders whose session is over, arms SL orders whose trigger is
crossed, and fills pending orders a live price has crossed.

Only a price received after an order was placed can fill it: the cached
price from before is one the order has already been checked against.
"""

from collections.abc import Callable
from datetime import datetime

from openticker.core.calendar.calendar import session_hours, square_off_at
from openticker.core.calendar.models import MarketCalendar
from openticker.core.orders.matching import match_resting
from openticker.core.orders.models import Order, OrderStatus
from openticker.events.bus import EventPublisher
from openticker.events.types import OrderCancelled, OrderFailed, OrderFilled
from openticker.ports.models import EXCHANGE_TIMEZONE, Instrument, Product, Tick
from openticker.ports.sandbox_port import SandboxPort


def execute_resting_orders(
    sandbox: SandboxPort,
    latest: Callable[[Instrument], Tick | None],
    events: EventPublisher,
    calendar: MarketCalendar,
    now: datetime,
) -> None:
    for order in sandbox.pending_orders():
        expiry = _expiry(order, calendar)
        if now >= expiry[0]:
            result = sandbox.expire_order(order.order_id, expiry[1], now)
            if result.status is OrderStatus.CANCELLED:
                events.publish(
                    OrderCancelled(
                        order_id=order.order_id,
                        symbol=order.instrument.symbol,
                        reason=expiry[1],
                        triggered_by=order.triggered_by,
                    )
                )
            continue
        tick = latest(order.instrument)
        if tick is None or tick.received_at <= order.placed_at:
            continue
        match = match_resting(order, tick.last_price)
        if match.triggered and not order.triggered:
            sandbox.arm_pending(order.order_id, now)
        if match.fill:
            _fill(sandbox, order, tick.last_price, events, now)


def _expiry(order: Order, calendar: MarketCalendar) -> tuple[datetime, str]:
    """When a pending order stops being valid, and why. Orders are day
    orders: MIS ones go at the intraday square-off, the rest at the close."""
    placed_on = order.placed_at.astimezone(EXCHANGE_TIMEZONE).date()
    hours = session_hours(placed_on, order.instrument.exchange, calendar)
    if hours is None:
        return order.placed_at, "expired: placed while the exchange was closed"
    if order.product is Product.MIS:
        return square_off_at(hours), "expired at the intraday square-off"
    return hours.closes_at, "expired at the session's close"


def _fill(
    sandbox: SandboxPort, order: Order, price: float, events: EventPublisher, now: datetime
) -> None:
    result = sandbox.fill_pending(order.order_id, price, now)
    if result.status is OrderStatus.FILLED and result.fill_price is not None:
        events.publish(
            OrderFilled(
                order_id=order.order_id,
                symbol=order.instrument.symbol,
                side=order.side.value,
                quantity=order.quantity,
                price=result.fill_price,
                triggered_by=order.triggered_by,
            )
        )
    elif result.status is OrderStatus.REJECTED:
        events.publish(
            OrderFailed(
                symbol=order.instrument.symbol,
                reason=result.reason or "rejected",
                triggered_by=order.triggered_by,
            )
        )
