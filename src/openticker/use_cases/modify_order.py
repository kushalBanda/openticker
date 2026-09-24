"""Change a pending order's quantity, price or trigger (ADR 11 in docs/adr).
The change is checked like a new order: shape, tick and lot, market hours,
and, when the quantity grows, the intraday cutoff and the capital cap. It
never fills the order: the next live price does, in openticker-serve."""

from datetime import datetime

from openticker.core.calendar.models import MarketCalendar
from openticker.core.orders.models import OrderChanges, OrderResult, OrderStatus
from openticker.core.orders.modify import ChangeRefused, apply_changes, describe_change
from openticker.core.orders.validation import validate_order
from openticker.core.risk.models import BreachReason
from openticker.events.bus import EventPublisher
from openticker.events.types import OrderModified, RiskBreached
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.use_cases.errors import UnknownOrderError
from openticker.use_cases.place_order import (
    capital_cap_breach,
    intraday_cutoff_reason,
    market_closed_reason,
)


def modify_order(
    order_id: str,
    changes: OrderChanges,
    broker: BrokerPort,
    events: EventPublisher,
    capital_cap: float | None,
    calendar: MarketCalendar,
    now: datetime,
    triggered_by: str,
) -> OrderResult:
    """PENDING: the order now rests at its new terms. Anything else says why
    the order was left as it was."""
    order = broker.get_order(order_id)
    if order is None:
        raise UnknownOrderError(f"no order {order_id!r}; get_orderbook lists them")
    try:
        request = apply_changes(order, changes)
    except ChangeRefused as exc:
        return _refused(order_id, str(exc))
    validation = validate_order(request, now.astimezone(EXCHANGE_TIMEZONE).date())
    if not validation.valid:
        return _refused(order_id, validation.reason or "invalid change")
    closed = market_closed_reason(request, calendar, now)
    if closed is not None:
        return _refused(order_id, closed)
    try:
        if request.quantity > order.quantity:
            cutoff = intraday_cutoff_reason(request, broker, calendar, now)
            if cutoff is not None:
                return _refused(order_id, cutoff)
            breach = (
                capital_cap_breach(request, broker, capital_cap)
                if capital_cap is not None
                else None
            )
            if breach is not None:
                events.publish(
                    RiskBreached(
                        symbol=order.instrument.symbol,
                        reason=BreachReason.CAPITAL_CAP,
                        detail=breach,
                    )
                )
                return _refused(order_id, breach)
        result = broker.modify_order(order_id, changes)
    except BrokerError as exc:
        return OrderResult(status=OrderStatus.FAILED, broker_order_id=order_id, reason=str(exc))
    if result.status is OrderStatus.PENDING:
        events.publish(
            OrderModified(
                order_id=order_id,
                symbol=order.instrument.symbol,
                change=describe_change(order, request),
                triggered_by=triggered_by,
            )
        )
    return result


def _refused(order_id: str, reason: str) -> OrderResult:
    return OrderResult(status=OrderStatus.REJECTED, broker_order_id=order_id, reason=reason)
