"""Close a sandbox position at the market (ADR 26 in docs/adr). The quantity is
what is held when the fill is written, not when it was asked for. A strategy
holding the position is not stopped: its runner finds the leg already flat
when it next exits."""

from datetime import datetime

from openticker.core.calendar.models import MarketCalendar
from openticker.core.orders.models import OrderRequest, OrderResult, OrderStatus, OrderType
from openticker.core.orders.sandbox import quote_is_fillable
from openticker.core.orders.validation import validate_order
from openticker.events.bus import EventPublisher
from openticker.events.types import OrderFailed, OrderFilled, OrderPlaced
from openticker.ports.models import EXCHANGE_TIMEZONE, Instrument, Position, Product, Quote, Side
from openticker.ports.sandbox_port import OrderSandbox
from openticker.use_cases.place_order import market_closed_reason


class NoOpenPositionError(LookupError):
    pass


def close_position(
    sandbox: OrderSandbox,
    instrument: Instrument,
    product: Product,
    events: EventPublisher,
    calendar: MarketCalendar,
    now: datetime,
    triggered_by: str,
) -> tuple[Position, OrderResult]:
    held = next(
        (
            position
            for position in sandbox.open_positions()
            if position.instrument.symbol == instrument.symbol
            and position.instrument.exchange == instrument.exchange
            and position.product == product
        ),
        None,
    )
    if held is None:
        raise NoOpenPositionError(
            f"no open {product} position in {instrument.symbol} on {instrument.exchange}; "
            "get_positions lists them"
        )
    return held, close_held(
        sandbox, held, sandbox.get_quote(instrument), events, calendar, now, triggered_by
    )


def close_held(
    sandbox: OrderSandbox,
    position: Position,
    quote: Quote | None,
    events: EventPublisher,
    calendar: MarketCalendar,
    now: datetime,
    triggered_by: str,
) -> OrderResult:
    """Refused, with the reason, when the contract can't trade (expired, an
    index), its exchange is closed or there is no fresh price."""
    instrument = position.instrument
    request = OrderRequest(
        instrument=instrument,
        side=Side.SELL if position.quantity > 0 else Side.BUY,
        quantity=abs(position.quantity),
        product=position.product,
        order_type=OrderType.MARKET,
        price=None,
        triggered_by=triggered_by,
    )
    validation = validate_order(request, now.astimezone(EXCHANGE_TIMEZONE).date())
    if not validation.valid:
        return _refused(events, instrument, validation.reason or "invalid order", triggered_by)
    closed = market_closed_reason(request, calendar, now)
    if closed is not None:
        return _refused(events, instrument, closed, triggered_by)
    if quote is None or not quote_is_fillable(quote):
        last = f" (last {quote.last_price})" if quote is not None else ""
        return _refused(
            events,
            instrument,
            f"no fresh price for {instrument.symbol}{last}; not closed",
            triggered_by,
        )
    result = sandbox.close_position(instrument, position.product, quote, now, triggered_by)
    order = sandbox.get_order(result.broker_order_id) if result.broker_order_id else None
    if result.status is not OrderStatus.FILLED or order is None or result.fill_price is None:
        return _refused(events, instrument, result.reason or result.status.value, triggered_by)
    events.publish(
        OrderPlaced(
            order_id=order.order_id,
            symbol=instrument.symbol,
            side=order.side.value,
            quantity=order.quantity,
            triggered_by=triggered_by,
        )
    )
    events.publish(
        OrderFilled(
            order_id=order.order_id,
            symbol=instrument.symbol,
            side=order.side.value,
            quantity=order.quantity,
            price=result.fill_price,
            triggered_by=triggered_by,
        )
    )
    return result


def _refused(
    events: EventPublisher, instrument: Instrument, reason: str, triggered_by: str
) -> OrderResult:
    events.publish(OrderFailed(symbol=instrument.symbol, reason=reason, triggered_by=triggered_by))
    return OrderResult(status=OrderStatus.REJECTED, broker_order_id=None, reason=reason)
