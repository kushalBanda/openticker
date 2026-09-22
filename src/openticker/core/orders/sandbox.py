"""Paper-trading arithmetic: when a quote can be filled against, what margin an
order blocks, and how a fill changes a net position. Pure (ADR 11 in docs/adr).

Margin is the order's value divided by a leverage that depends on what is
traded; closing a position releases the margin it blocked, and realized
profit or loss goes to available cash. Charges and taxes are not modelled.
"""

import math
from dataclasses import dataclass, replace

from openticker.ports.models import Instrument, InstrumentType, Product, Quote, Side


@dataclass(frozen=True)
class Leverage:
    equity_intraday: float = 5.0
    equity_delivery: float = 1.0
    futures: float = 10.0
    option_buy: float = 1.0
    option_sell: float = 1.0


@dataclass(frozen=True)
class NetPosition:
    quantity: int  # signed: positive long, negative short
    average_price: float  # of the open quantity; 0 when flat
    margin_blocked: float
    realized_pnl: float


@dataclass(frozen=True)
class FillOutcome:
    position: NetPosition
    opened_quantity: int  # the part of the fill that opened or added to a position
    margin_required: float  # for the opened part
    margin_released: float  # by the closed part
    realized_pnl: float  # by the closed part


FLAT = NetPosition(quantity=0, average_price=0.0, margin_blocked=0.0, realized_pnl=0.0)


def quote_is_fillable(quote: Quote) -> bool:
    """A price to fill at: positive, finite, and inside the day's own range
    when the quote carries one. A last price outside its own day high/low is
    an old trade the broker is still reporting, not today's market."""
    price = quote.last_price
    if not (math.isfinite(price) and price > 0):
        return False
    low, high = quote.day_low, quote.day_high
    if low is not None and high is not None and low > 0 and high > 0:
        return low <= price <= high
    return True


def leverage_for(instrument: Instrument, product: Product, side: Side, table: Leverage) -> float:
    match instrument.instrument_type:
        case InstrumentType.EQ:
            return table.equity_intraday if product is Product.MIS else table.equity_delivery
        case InstrumentType.FUT:
            return table.futures
        case InstrumentType.CE | InstrumentType.PE:
            return table.option_buy if side is Side.BUY else table.option_sell
    raise ValueError(f"{instrument.symbol} ({instrument.instrument_type}) is not tradeable")


def apply_fill(
    position: NetPosition, side: Side, quantity: int, price: float, leverage: float
) -> FillOutcome:
    """The position after filling `quantity` at `price`. A fill against the
    position closes first (realizing P&L at the position's average price) and
    any remainder opens the other way at `price`."""
    signed = quantity if side is Side.BUY else -quantity
    held = position.quantity
    closing = min(abs(signed), abs(held)) if held * signed < 0 else 0
    opening = abs(signed) - closing

    realized = 0.0
    released = 0.0
    margin = position.margin_blocked
    average = position.average_price
    if closing:
        direction = 1 if held > 0 else -1
        realized = (price - average) * closing * direction
        released = position.margin_blocked * closing / abs(held)
        margin -= released
    remaining = held + (closing if held < 0 else -closing)
    if remaining == 0:
        average, margin = 0.0, 0.0

    required = price * opening / leverage if opening else 0.0
    if opening:
        new_quantity = remaining + (opening if signed > 0 else -opening)
        average = (average * abs(remaining) + price * opening) / abs(new_quantity)
        margin += required
    else:
        new_quantity = remaining

    return FillOutcome(
        position=replace(
            position,
            quantity=new_quantity,
            average_price=average,
            margin_blocked=margin,
            realized_pnl=position.realized_pnl + realized,
        ),
        opened_quantity=opening,
        margin_required=required,
        margin_released=released,
        realized_pnl=realized,
    )
