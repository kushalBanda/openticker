from datetime import UTC, datetime

import pytest

from openticker.core.orders.sandbox import (
    FLAT,
    Leverage,
    NetPosition,
    apply_fill,
    leverage_for,
    paper_margin,
    quote_is_fillable,
)
from openticker.ports.models import InstrumentType, Product, Quote, Side
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.options import option

NOW = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)


def _quote(price: float, low: float | None = None, high: float | None = None) -> Quote:
    return Quote(FAKE_INSTRUMENT, price, NOW, day_low=low, day_high=high)


def test_a_last_price_outside_its_own_day_range_is_not_fillable() -> None:
    assert quote_is_fillable(_quote(1250, 1240, 1262))
    assert not quote_is_fillable(_quote(1047.6, 1262, 1290))  # an old trade still reported
    assert quote_is_fillable(_quote(1047.6))  # no range to check against
    assert not quote_is_fillable(_quote(0.0))


def test_leverage_depends_on_what_is_traded() -> None:
    table = Leverage()
    call = option("NIFTY", NOW.date(), 25000, InstrumentType.CE)

    assert leverage_for(FAKE_INSTRUMENT, Product.MIS, Side.BUY, table) == 5
    assert leverage_for(FAKE_INSTRUMENT, Product.CNC, Side.BUY, table) == 1
    assert leverage_for(call, Product.NRML, Side.SELL, table) == 1


def test_opening_and_adding_average_the_price_and_block_margin() -> None:
    first = apply_fill(FLAT, Side.BUY, 10, 100.0, leverage=5)
    second = apply_fill(first.position, Side.BUY, 10, 110.0, leverage=5)

    assert first.margin_required == 200.0
    assert second.position == NetPosition(20, 105.0, 420.0, 0.0)


def test_partial_close_realizes_and_releases_its_share_of_margin() -> None:
    held = NetPosition(20, 105.0, 420.0, 0.0)

    outcome = apply_fill(held, Side.SELL, 5, 120.0, leverage=5)

    assert (outcome.realized_pnl, outcome.margin_released, outcome.opened_quantity) == (
        75.0,
        105.0,
        0,
    )
    assert outcome.position == NetPosition(15, 105.0, 315.0, 75.0)


def test_short_profits_when_price_falls_and_full_close_goes_flat() -> None:
    short = apply_fill(FLAT, Side.SELL, 10, 100.0, leverage=1).position

    closed = apply_fill(short, Side.BUY, 10, 90.0, leverage=1)

    assert short.quantity == -10
    assert closed.realized_pnl == 100.0
    assert closed.position == NetPosition(0, 0.0, 0.0, 100.0)


def test_fill_through_zero_closes_then_opens_the_other_way() -> None:
    held = NetPosition(10, 100.0, 200.0, 0.0)

    outcome = apply_fill(held, Side.SELL, 15, 110.0, leverage=5)

    assert outcome.realized_pnl == 100.0
    assert outcome.opened_quantity == 5
    assert outcome.margin_required == pytest.approx(110.0)
    assert outcome.position == NetPosition(-5, 110.0, pytest.approx(110.0), 100.0)  # type: ignore[arg-type]


def test_paper_margin_blocks_only_what_opens() -> None:
    long = NetPosition(quantity=10, average_price=100.0, margin_blocked=1000.0, realized_pnl=0.0)

    adding = paper_margin(long, Side.BUY, 10, 110.0, 1.0, available=500.0)
    closing = paper_margin(long, Side.SELL, 10, 110.0, 1.0, available=0.0)
    flipping = paper_margin(long, Side.SELL, 15, 110.0, 1.0, available=0.0)

    assert (adding.required, adding.released, adding.fits) == (1100.0, 0.0, False)
    assert (closing.required, closing.released, closing.fits) == (0.0, 1000.0, True)
    # the 5 opened short are covered by the 1,000 released plus 100 realized
    assert (flipping.required, flipping.fits) == (550.0, True)
