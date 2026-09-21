"""Black-76 pricing, Greeks and implied volatility. Pure math, stdlib only.

Indian index and stock options are priced off the forward (the futures price),
not spot, so Black-76 rather than Black-Scholes (ADR 16 in docs/adr).
"""

import math

from openticker.core.options.models import Greeks, GreeksModel
from openticker.ports.models import InstrumentType

# Below this, the model's denominators blow up. About 53 minutes.
MIN_YEARS_TO_EXPIRY = 0.0001

_IV_LOW = 1e-4
_IV_HIGH = 5.0  # 500%: anything above is a bad price, not a volatility
_IV_PRICE_TOLERANCE = 1e-6
_IV_MAX_ITERATIONS = 200
_DAYS_PER_YEAR = 365.0


class GreeksInputError(ValueError):
    """Forward, strike or time to expiry is not positive, or the type isn't CE/PE."""


def black76_price(
    option_type: InstrumentType,
    forward: float,
    strike: float,
    years: float,
    rate: float,
    volatility: float,
) -> float:
    _check(option_type, forward, strike, years)
    discount = math.exp(-rate * years)
    d1, d2 = _d1_d2(forward, strike, years, volatility)
    if option_type is InstrumentType.CE:
        return discount * (forward * _cdf(d1) - strike * _cdf(d2))
    return discount * (strike * _cdf(-d2) - forward * _cdf(-d1))


def implied_volatility(
    option_type: InstrumentType,
    price: float,
    forward: float,
    strike: float,
    years: float,
    rate: float,
) -> float | None:
    """The volatility at which Black-76 reproduces `price`, or None when no
    volatility can: the price is at or below intrinsic value (no time value to
    solve from) or above the most an option can be worth."""
    _check(option_type, forward, strike, years)
    discount = math.exp(-rate * years)
    intrinsic = discount * max(
        forward - strike if option_type is InstrumentType.CE else strike - forward, 0.0
    )
    ceiling = discount * (forward if option_type is InstrumentType.CE else strike)
    if price <= intrinsic + _IV_PRICE_TOLERANCE or price >= ceiling:
        return None

    # Price rises monotonically with volatility, so bisection always converges.
    low, high = _IV_LOW, _IV_HIGH
    if black76_price(option_type, forward, strike, years, rate, high) < price:
        return None
    for _ in range(_IV_MAX_ITERATIONS):
        middle = (low + high) / 2
        error = black76_price(option_type, forward, strike, years, rate, middle) - price
        if abs(error) < _IV_PRICE_TOLERANCE:
            return middle
        if error > 0:
            high = middle
        else:
            low = middle
    return (low + high) / 2


def greeks(
    option_type: InstrumentType,
    price: float,
    forward: float,
    strike: float,
    years: float,
    rate: float,
) -> Greeks:
    """Greeks at the implied volatility of `price`. When there is none, delta
    comes from moneyness alone (in the money: the full discounted delta, out of
    it: zero) and every other Greek is zero."""
    _check(option_type, forward, strike, years)
    discount = math.exp(-rate * years)
    volatility = implied_volatility(option_type, price, forward, strike, years, rate)
    is_call = option_type is InstrumentType.CE
    if volatility is None:
        in_the_money = forward > strike if is_call else strike > forward
        delta = (discount if is_call else -discount) if in_the_money else 0.0
        return Greeks(GreeksModel.INTRINSIC, None, delta, 0.0, 0.0, 0.0, 0.0)

    d1, _ = _d1_d2(forward, strike, years, volatility)
    root_years = math.sqrt(years)
    density = _pdf(d1)
    model_price = black76_price(option_type, forward, strike, years, rate, volatility)
    delta = discount * _cdf(d1) if is_call else -discount * _cdf(-d1)
    gamma = discount * density / (forward * volatility * root_years)
    vega = discount * forward * density * root_years
    # d(price)/d(time passing) = r * price - decay; same form for calls and puts.
    theta = rate * model_price - discount * forward * density * volatility / (2 * root_years)
    rho = -years * model_price
    return Greeks(
        model=GreeksModel.IMPLIED,
        implied_volatility=volatility,
        delta=delta,
        gamma=gamma,
        theta=theta / _DAYS_PER_YEAR,
        vega=vega / 100,
        rho=rho / 100,
    )


def _d1_d2(forward: float, strike: float, years: float, volatility: float) -> tuple[float, float]:
    spread = volatility * math.sqrt(years)
    d1 = (math.log(forward / strike) + 0.5 * volatility * volatility * years) / spread
    return d1, d1 - spread


def _check(option_type: InstrumentType, forward: float, strike: float, years: float) -> None:
    if option_type not in (InstrumentType.CE, InstrumentType.PE):
        raise GreeksInputError(f"not an option type: {option_type}")
    if not (forward > 0 and strike > 0 and years > 0):
        raise GreeksInputError(
            f"forward, strike and years must be positive, got {forward}, {strike}, {years}"
        )


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
