import math

import pytest

from openticker.core.options.greeks import (
    GreeksInputError,
    black76_price,
    greeks,
    implied_volatility,
)
from openticker.core.options.models import GreeksModel
from openticker.ports.models import InstrumentType

CE, PE = InstrumentType.CE, InstrumentType.PE


def _cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def test_at_the_money_call_matches_closed_form() -> None:
    # F = K, r = 0: C = F * (2 N(sigma sqrt(T) / 2) - 1)
    assert black76_price(CE, 100, 100, 1.0, 0.0, 0.2) == pytest.approx(100 * (2 * _cdf(0.1) - 1))


def test_put_call_parity_holds_with_a_rate() -> None:
    call = black76_price(CE, 25100, 25000, 0.05, 0.065, 0.14)
    put = black76_price(PE, 25100, 25000, 0.05, 0.065, 0.14)

    assert call - put == pytest.approx(math.exp(-0.065 * 0.05) * (25100 - 25000))


@pytest.mark.parametrize(
    ("option_type", "strike"), [(CE, 24500), (CE, 25500), (PE, 24500), (PE, 25500)]
)
def test_implied_volatility_recovers_the_pricing_volatility(
    option_type: InstrumentType, strike: float
) -> None:
    price = black76_price(option_type, 25000, strike, 0.04, 0.0, 0.18)

    solved = implied_volatility(option_type, price, 25000, strike, 0.04, 0.0)

    assert solved == pytest.approx(0.18, abs=1e-5)


def test_price_at_intrinsic_has_no_implied_volatility() -> None:
    assert implied_volatility(CE, 500.0, 25500, 25000, 0.04, 0.0) is None


def test_price_above_the_forward_has_no_implied_volatility() -> None:
    assert implied_volatility(CE, 26000.0, 25000, 25000, 0.04, 0.0) is None


def test_no_time_value_falls_back_to_intrinsic_delta() -> None:
    deep_call = greeks(CE, 500.0, 25500, 25000, 0.04, 0.0)
    worthless_put = greeks(PE, 0.0000001, 25500, 25000, 0.04, 0.0)

    assert deep_call.model is GreeksModel.INTRINSIC
    assert (deep_call.implied_volatility, deep_call.delta, deep_call.gamma) == (None, 1.0, 0.0)
    assert worthless_put.delta == 0.0


def test_greeks_match_finite_differences_in_trader_units() -> None:
    forward, strike, years, rate, vol = 25000.0, 25200.0, 10 / 365, 0.06, 0.15
    price = black76_price(CE, forward, strike, years, rate, vol)

    result = greeks(CE, price, forward, strike, years, rate)

    def at(f: float = forward, t: float = years, r: float = rate, v: float = vol) -> float:
        return black76_price(CE, f, strike, t, r, v)

    assert result.model is GreeksModel.IMPLIED
    assert result.implied_volatility == pytest.approx(vol, abs=1e-5)
    assert result.delta == pytest.approx((at(f=forward + 1) - at(f=forward - 1)) / 2, rel=1e-3)
    assert result.gamma == pytest.approx(
        at(f=forward + 1) - 2 * price + at(f=forward - 1), rel=1e-2
    )
    hour = 1 / (365 * 24)
    per_day = (at(t=years - hour) - at(t=years + hour)) / (2 * hour) / 365
    assert result.theta == pytest.approx(per_day, rel=1e-3)
    assert result.vega == pytest.approx(at(v=vol + 0.01) - price, rel=2e-2)  # per 1 point
    assert result.rho == pytest.approx(at(r=rate + 0.01) - price, rel=2e-2)  # per 1 point
    assert result.theta < 0 < result.vega


def test_put_delta_is_negative_and_call_minus_put_delta_is_the_discount() -> None:
    call = greeks(CE, black76_price(CE, 25000, 25000, 0.1, 0.05, 0.2), 25000, 25000, 0.1, 0.05)
    put = greeks(PE, black76_price(PE, 25000, 25000, 0.1, 0.05, 0.2), 25000, 25000, 0.1, 0.05)

    assert -1 < put.delta < 0 < call.delta < 1
    assert call.delta - put.delta == pytest.approx(math.exp(-0.05 * 0.1))


@pytest.mark.parametrize(
    ("option_type", "forward", "strike", "years"),
    [(CE, 0, 100, 1), (CE, 100, 0, 1), (CE, 100, 100, 0), (InstrumentType.FUT, 100, 100, 1)],
)
def test_rejects_inputs_the_model_cannot_price(
    option_type: InstrumentType, forward: float, strike: float, years: float
) -> None:
    with pytest.raises(GreeksInputError):
        black76_price(option_type, forward, strike, years, 0.0, 0.2)
