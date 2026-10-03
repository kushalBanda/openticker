from datetime import UTC, date, datetime, timedelta
from itertools import pairwise

import pytest

from openticker.core.options.chain import expires_at
from openticker.core.options.payoff import Payoff, PayoffInputError, PayoffLeg, payoff
from openticker.ports.models import InstrumentType, Side

CE, PE, FUT = InstrumentType.CE, InstrumentType.PE, InstrumentType.FUT
BUY, SELL = Side.BUY, Side.SELL
EXPIRY = date(2026, 9, 29)
NOW = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST
SPOT = 24812.35


def leg(
    kind: InstrumentType, strike: float | None, side: Side, price: float, qty: int = 75
) -> PayoffLeg:
    return PayoffLeg(kind, strike, EXPIRY, side, qty, price)


IRON_FLY = [
    leg(CE, 24800, SELL, 128.05),
    leg(PE, 24800, SELL, 139.20),
    leg(CE, 25400, BUY, 3.10),
    leg(PE, 24200, BUY, 6.15),
]


def test_long_call_at_expiry_is_hockey_stick() -> None:
    result = payoff([leg(CE, 24800, BUY, 100, qty=1)], SPOT, NOW, {0: 0.12})

    below = [p for p in result.points if p.underlying <= 24800]
    assert {p.at_expiry for p in below} == {-100.0}
    above = [p for p in result.points if p.underlying > 24900]
    for a, b in pairwise(above):
        assert b.at_expiry - a.at_expiry == pytest.approx(b.underlying - a.underlying, abs=0.02)
    assert result.max_profit is None
    assert result.max_loss == -100.0
    assert result.breakevens == (24900.0,)
    assert result.net_premium == -100.0


def test_iron_fly_matches_mock_numbers() -> None:
    result = payoff(IRON_FLY, SPOT, NOW, dict.fromkeys(range(4), 0.11))

    assert result.net_premium == 19350.0
    assert result.max_profit == 19350.0
    assert result.max_loss == -25650.0
    assert result.breakevens == (24542.0, 25058.0)
    # The range takes in both wings.
    assert result.points[0].underlying < 24200 and result.points[-1].underlying > 25400


def test_short_straddle_losses_are_unbounded() -> None:
    result = payoff(IRON_FLY[:2], SPOT, NOW, {0: 0.11, 1: 0.11})

    assert result.max_loss is None
    assert result.max_profit == (128.05 + 139.20) * 75


def test_futures_leg_is_linear() -> None:
    future = PayoffLeg(FUT, None, date(2026, 10, 27), BUY, 75, 24851.10)
    result = payoff([future], SPOT, NOW, {})

    for point in result.points:
        assert point.at_expiry == pytest.approx((point.underlying - 24851.10) * 75, abs=1)
        assert point.today == point.at_expiry
    assert result.breakevens == (24851.1,)
    assert result.max_profit is None
    assert result.max_loss == -24851.10 * 75
    assert result.net_premium == 0
    assert result.net_delta == pytest.approx(75)


def test_today_curve_is_none_without_volatility() -> None:
    result = payoff(IRON_FLY, SPOT, NOW, {0: 0.11, 1: 0.11, 2: None, 3: 0.14})

    assert all(point.today is None for point in result.points)
    assert result.net_delta is None
    assert result.max_profit == 19350.0  # expiry figures still stand


def test_today_converges_to_expiry_as_time_runs_out() -> None:
    week = payoff(IRON_FLY, SPOT, NOW, dict.fromkeys(range(4), 0.11))
    last_minute = payoff(
        IRON_FLY, SPOT, expires_at(EXPIRY) - timedelta(minutes=1), dict.fromkeys(range(4), 0.11)
    )

    def gap(result: Payoff) -> float:
        return max(abs((p.today or 0) - p.at_expiry) for p in result.points)

    assert gap(last_minute) < gap(week) / 10
    # Today a short fly makes less at the strike than it will at expiry.
    at_strike = min(week.points, key=lambda p: abs(p.underlying - 24800))
    assert at_strike.today is not None and at_strike.today < at_strike.at_expiry


def test_iron_fly_is_nearly_delta_neutral_at_its_strike() -> None:
    result = payoff(IRON_FLY, 24800, NOW, dict.fromkeys(range(4), 0.11))

    assert result.net_delta is not None and abs(result.net_delta) < 5


def test_rejects_empty_legs_and_mixed_expiries_for_today() -> None:
    with pytest.raises(PayoffInputError, match="no legs"):
        payoff([], SPOT, NOW, {})
    later = PayoffLeg(CE, 25000, date(2026, 10, 6), BUY, 75, 90)
    with pytest.raises(PayoffInputError, match="one expiry"):
        payoff([IRON_FLY[0], later], SPOT, NOW, {0: 0.1, 1: 0.1})
    with pytest.raises(PayoffInputError, match="already expired"):
        payoff(IRON_FLY, SPOT, expires_at(EXPIRY), {})


def test_rejects_a_stock_leg_and_a_bad_quantity() -> None:
    with pytest.raises(PayoffInputError, match="only options and futures"):
        payoff([PayoffLeg(InstrumentType.EQ, None, EXPIRY, BUY, 1, 10)], SPOT, NOW, {})
    with pytest.raises(PayoffInputError, match="quantity"):
        payoff([leg(CE, 24800, BUY, 10, qty=0)], SPOT, NOW, {})
