from datetime import UTC, datetime

import pytest

from openticker.core.orders.fills import (
    FillSettings,
    market_price,
    marketable_limit_price,
    resting_limit_fills,
)
from openticker.ports.models import Quote, Side
from tests.fixtures.fake_broker import FAKE_INSTRUMENT

NOW = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)
ONE_TICK = FillSettings(slippage_ticks=1)
TICK = FAKE_INSTRUMENT.tick_size


def quote(last: float, bid: float | None = None, ask: float | None = None) -> Quote:
    return Quote(FAKE_INSTRUMENT, last, NOW, bid=bid, ask=ask)


def test_buy_pays_the_ask() -> None:
    assert market_price(Side.BUY, quote(100.0, 99.9, 100.2), TICK, ONE_TICK) == 100.2


def test_sell_gets_the_bid() -> None:
    assert market_price(Side.SELL, quote(100.0, 99.9, 100.2), TICK, ONE_TICK) == 99.9


@pytest.mark.parametrize(("side", "expected"), [(Side.BUY, 100.1), (Side.SELL, 99.9)])
def test_without_a_book_the_last_price_moves_ticks_against_the_order(
    side: Side, expected: float
) -> None:
    two_ticks = FillSettings(slippage_ticks=2)

    assert market_price(side, quote(100.0), TICK, two_ticks) == expected


def test_an_empty_side_of_the_book_counts_as_no_book() -> None:
    assert market_price(Side.BUY, quote(100.0, bid=99.9, ask=0.0), TICK, ONE_TICK) == 100.05


def test_a_sell_never_fills_below_one_tick() -> None:
    assert market_price(Side.SELL, quote(0.05), TICK, ONE_TICK) == TICK


def test_a_limit_through_the_market_fills_at_the_market() -> None:
    assert (
        marketable_limit_price(Side.BUY, 101.0, quote(100.0, 99.9, 100.2), TICK, ONE_TICK) == 100.2
    )
    assert (
        marketable_limit_price(Side.SELL, 99.0, quote(100.0, 99.9, 100.2), TICK, ONE_TICK) == 99.9
    )


def test_a_limit_short_of_the_market_rests() -> None:
    assert (
        marketable_limit_price(Side.BUY, 100.1, quote(100.0, 99.9, 100.2), TICK, ONE_TICK) is None
    )
    assert (
        marketable_limit_price(Side.SELL, 100.0, quote(100.0, 99.9, 100.2), TICK, ONE_TICK) is None
    )


@pytest.mark.parametrize(
    ("side", "last", "fills"),
    [(Side.BUY, 99.95, True), (Side.BUY, 100.0, False),
     (Side.SELL, 100.05, True), (Side.SELL, 100.0, False)],
)  # fmt: skip
def test_a_resting_limit_fills_only_when_traded_through(
    side: Side, last: float, fills: bool
) -> None:
    assert resting_limit_fills(side, 100.0, last) is fills


def test_slippage_ticks_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="slippage_ticks"):
        FillSettings(slippage_ticks=-1)
