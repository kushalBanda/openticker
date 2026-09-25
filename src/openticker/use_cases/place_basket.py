"""Several sandbox orders placed as one set, buys first (ADR 26 in docs/adr).
Each goes through place_order on its own, one after another: the set is not
atomic, and one refused order doesn't stop the rest."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from openticker.core.calendar.models import MarketCalendar
from openticker.core.orders.basket import basket_sequence
from openticker.core.orders.models import OrderRequest, OrderResult, OrderStatus, OrderType
from openticker.events.bus import EventPublisher
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import Exchange, Product, Side
from openticker.use_cases.errors import BatchTooLargeError
from openticker.use_cases.place_order import place_order
from openticker.use_cases.resolve_instrument import UnknownInstrumentError, resolve_instrument

# Keeps every answer bounded (ADR 8 in docs/adr).
MAX_BASKET = 50


@dataclass(frozen=True)
class BasketOrder:
    """One order of a basket as asked for, before its symbol is looked up."""

    symbol: str
    exchange: Exchange
    side: Side
    quantity: int
    product: Product
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    trigger_price: float | None = None


@dataclass(frozen=True)
class BasketPlacement:
    order: BasketOrder
    result: OrderResult


def place_basket(
    orders: Sequence[BasketOrder],
    broker: BrokerPort,
    events: EventPublisher,
    capital_cap: float | None,
    calendar: MarketCalendar,
    now: datetime,
    triggered_by: str,
) -> list[BasketPlacement]:
    """Results in placing order. An order whose symbol isn't known is
    REJECTED with the reason and the rest still go."""
    if len(orders) > MAX_BASKET:
        raise BatchTooLargeError(f"{len(orders)} orders in the basket; at most {MAX_BASKET}")
    placements: list[BasketPlacement] = []
    for index in basket_sequence([order.side for order in orders]):
        order = orders[index]
        try:
            instrument = resolve_instrument(order.symbol, order.exchange.value)
        except UnknownInstrumentError as exc:
            result = OrderResult(status=OrderStatus.REJECTED, broker_order_id=None, reason=str(exc))
        else:
            request = OrderRequest(
                instrument=instrument,
                side=order.side,
                quantity=order.quantity,
                product=order.product,
                order_type=order.order_type,
                price=order.price,
                trigger_price=order.trigger_price,
                triggered_by=triggered_by,
            )
            result = place_order(request, broker, events, capital_cap, calendar, now)
        placements.append(BasketPlacement(order=order, result=result))
    return placements
