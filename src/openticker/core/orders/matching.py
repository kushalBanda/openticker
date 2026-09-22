"""When a resting order fills against a live price. Pure (ADR 11 in docs/adr).

A crossed order fills at the live price, which is at least as good as its
limit: a buy limit at 100 with the market at 98 fills at 98.

- LIMIT: a buy fills at or below its price, a sell at or above.
- SL-M: a buy fills once the price rises to its trigger, a sell once it
  falls to it, at the market.
- SL: the trigger arms it the same way; from then on it rests as a LIMIT at
  its price, and stays armed even if the price moves back.
"""

from dataclasses import dataclass

from openticker.core.orders.models import Order, OrderType
from openticker.ports.models import Side


@dataclass(frozen=True)
class Match:
    fill: bool
    triggered: bool  # SL only: the trigger has been crossed, now or before


def match_resting(order: Order, last_price: float) -> Match:
    buying = order.side is Side.BUY
    match order.order_type:
        case OrderType.LIMIT:
            return Match(fill=_limit_crossed(buying, order.price, last_price), triggered=False)
        case OrderType.SL_M:
            return Match(
                fill=_trigger_crossed(buying, order.trigger_price, last_price), triggered=False
            )
        case OrderType.SL:
            armed = order.triggered or _trigger_crossed(buying, order.trigger_price, last_price)
            return Match(
                fill=armed and _limit_crossed(buying, order.price, last_price), triggered=armed
            )
    return Match(fill=False, triggered=False)


def trigger_crossed(order_side: Side, trigger_price: float, last_price: float) -> bool:
    """An SL or SL-M order whose trigger the market is already past: exchanges
    refuse these at placement."""
    return _trigger_crossed(order_side is Side.BUY, trigger_price, last_price)


def limit_crossed(order_side: Side, price: float, last_price: float) -> bool:
    return _limit_crossed(order_side is Side.BUY, price, last_price)


def _limit_crossed(buying: bool, price: float | None, last_price: float) -> bool:
    if price is None:
        return False
    return last_price <= price if buying else last_price >= price


def _trigger_crossed(buying: bool, trigger: float | None, last_price: float) -> bool:
    if trigger is None:
        return False
    return last_price >= trigger if buying else last_price <= trigger
