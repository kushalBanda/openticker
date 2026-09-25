"""When a resting order fills against a live price, and at what price.
Pure (ADR 11, ADR 28 in docs/adr).

- LIMIT: fills only when the market trades through its price (a buy below
  it, a sell above it), and then at its price: the order was waiting in the
  book, and at its price exactly it may be behind others in the queue.
- SL-M: a buy fills once the price rises to its trigger, a sell once it
  falls to it, at the market: a streamed price has no book, so the last
  price moved `slippage_ticks` against the order.
- SL: the trigger arms it the same way; from then on it rests as a LIMIT at
  its price, and stays armed even if the price moves back.
"""

from dataclasses import dataclass

from openticker.core.orders.fills import FillSettings, resting_limit_fills, slipped
from openticker.core.orders.models import Order, OrderType
from openticker.ports.models import Side


@dataclass(frozen=True)
class Match:
    fill: bool
    triggered: bool  # SL only: the trigger has been crossed, now or before
    price: float | None = None  # what it fills at, when it fills


def match_resting(order: Order, last_price: float, settings: FillSettings) -> Match:
    buying = order.side is Side.BUY
    match order.order_type:
        case OrderType.LIMIT:
            return _at_limit(order, last_price, triggered=False)
        case OrderType.SL_M:
            if _trigger_crossed(buying, order.trigger_price, last_price):
                price = slipped(order.side, last_price, order.instrument.tick_size, settings)
                return Match(fill=True, triggered=False, price=price)
            return Match(fill=False, triggered=False)
        case OrderType.SL:
            armed = order.triggered or _trigger_crossed(buying, order.trigger_price, last_price)
            if armed:
                return _at_limit(order, last_price, triggered=True)
            return Match(fill=False, triggered=False)
    return Match(fill=False, triggered=False)


def _at_limit(order: Order, last_price: float, triggered: bool) -> Match:
    if order.price is not None and resting_limit_fills(order.side, order.price, last_price):
        return Match(fill=True, triggered=triggered, price=order.price)
    return Match(fill=False, triggered=triggered)


def trigger_crossed(order_side: Side, trigger_price: float, last_price: float) -> bool:
    """An SL or SL-M order whose trigger the market is already past: exchanges
    refuse these at placement."""
    return _trigger_crossed(order_side is Side.BUY, trigger_price, last_price)


def _trigger_crossed(buying: bool, trigger: float | None, last_price: float) -> bool:
    if trigger is None:
        return False
    return last_price >= trigger if buying else last_price <= trigger
