"""The price a paper order fills at. Pure (ADR 28 in docs/adr).

A market order pays the other side of the book: a buy the best ask, a sell
the best bid. A quote without a book (a streamed tick, a thin contract) has
only its last price, so the order pays that moved `slippage_ticks` against
it. A resting limit fills only when the market trades through it: at its
limit exactly, the order may still be waiting behind others in the queue.
"""

from dataclasses import dataclass

from openticker.ports.models import Quote, Side


@dataclass(frozen=True)
class FillSettings:
    slippage_ticks: int = 1  # only when the quote carries no bid or ask

    def __post_init__(self) -> None:
        if self.slippage_ticks < 0:
            raise ValueError(f"slippage_ticks must be 0 or more, got {self.slippage_ticks}")


def market_price(side: Side, quote: Quote, tick_size: float, settings: FillSettings) -> float:
    book = quote.ask if side is Side.BUY else quote.bid
    if book is not None and book > 0:
        return book
    return slipped(side, quote.last_price, tick_size, settings)


def slipped(side: Side, last_price: float, tick_size: float, settings: FillSettings) -> float:
    """The last price moved against the order, never below one tick."""
    move = settings.slippage_ticks * tick_size
    if side is Side.BUY:
        return round(last_price + move, 10)
    return round(max(last_price - move, tick_size), 10)


def marketable_limit_price(
    side: Side, limit: float, quote: Quote, tick_size: float, settings: FillSettings
) -> float | None:
    """A LIMIT placed through the market fills at once at the market price,
    which is at least as good as its limit. None: it rests."""
    price = market_price(side, quote, tick_size, settings)
    reachable = price <= limit if side is Side.BUY else price >= limit
    return price if reachable else None


def resting_limit_fills(side: Side, limit: float, last_price: float) -> bool:
    """Strictly through the limit; it then fills at the limit."""
    return last_price < limit if side is Side.BUY else last_price > limit
