"""Payoff of a set of option and futures legs on one underlying, at expiry and
today. Pure: prices, volatilities and the clock are passed in (ADR 38 in
docs/adr).

At expiry an option is worth its intrinsic value and a future the underlying,
so the curve is straight between strikes and every figure is exact: the
breakevens are where it crosses zero, the most it makes and loses are at a
strike or at zero, and it is unbounded only when it still slopes above the
highest strike. Today's curve prices each option with Black-76 at its own
volatility, the underlying standing in for the forward, as the volatility was
solved (ADR 16).
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from itertools import pairwise

from openticker.core.options.chain import ChainInputError, years_to_expiry
from openticker.core.options.greeks import black76_price
from openticker.ports.models import InstrumentType, Side

_OPTION_TYPES = (InstrumentType.CE, InstrumentType.PE)


class PayoffInputError(ValueError):
    """No legs, a leg that isn't an option or a future, options of more than
    one expiry, or an expired one."""


@dataclass(frozen=True)
class PayoffLeg:
    instrument_type: InstrumentType  # CE, PE or FUT
    strike: float | None  # None for FUT
    expiry: date
    side: Side
    quantity: int  # units
    entry_price: float  # premium paid or received; the future's price


@dataclass(frozen=True)
class PayoffPoint:
    underlying: float
    at_expiry: float
    today: float | None  # None when a leg has no volatility to price it


@dataclass(frozen=True)
class Payoff:
    points: tuple[PayoffPoint, ...]  # evenly spaced across the range
    breakevens: tuple[float, ...]  # at expiry, ascending
    max_profit: float | None  # the highest P&L at expiry; None: unbounded
    max_loss: float | None  # the lowest P&L at expiry, negative for a loss; None: unbounded
    net_premium: float  # positive: credit
    net_delta: float | None  # rupees per point of the underlying, today; None without volatility


def payoff(
    legs: Sequence[PayoffLeg],
    spot: float,
    now: datetime,
    volatility: Mapping[int, float | None],
    rate: float = 0.0,
    span: float = 0.08,
    steps: int = 161,
) -> Payoff:
    """`volatility` maps a leg's index to its implied volatility (a fraction);
    futures need none. The range is `span` either side of `spot`, widened to
    take in every strike."""
    _check(legs, spot, steps)
    years = _years(legs, now)
    priced = all(
        volatility.get(index) is not None
        for index, leg in enumerate(legs)
        if leg.instrument_type in _OPTION_TYPES
    )

    def at_expiry(underlying: float) -> float:
        return sum(_expiry_value(leg, underlying) for leg in legs)

    def today(underlying: float) -> float:
        total = 0.0
        for index, leg in enumerate(legs):
            if leg.instrument_type is InstrumentType.FUT or years is None:
                total += _expiry_value(leg, underlying)
                continue
            assert leg.strike is not None
            vol = volatility[index]
            assert vol is not None
            value = black76_price(leg.instrument_type, underlying, leg.strike, years, rate, vol)
            total += _signed(leg) * (value - leg.entry_price) * leg.quantity
        return total

    strikes = sorted({leg.strike for leg in legs if leg.strike is not None})
    low, high = _range(spot, span, strikes)
    width = (high - low) / (steps - 1)
    points = tuple(
        PayoffPoint(
            underlying=round(x, 2),
            at_expiry=round(at_expiry(x), 2),
            today=round(today(x), 2) if priced else None,
        )
        for x in (low + width * n for n in range(steps))
    )

    # Straight between kinks: the extremes and the zero crossings are exact.
    kinks = [0.0, *strikes]
    values = [at_expiry(x) for x in kinks]
    slope = sum(
        _signed(leg) * leg.quantity
        for leg in legs
        if leg.instrument_type in (InstrumentType.CE, InstrumentType.FUT)
    )
    h = spot * 1e-4
    return Payoff(
        points=points,
        breakevens=_zeros(kinks, values, slope),
        max_profit=None if slope > 0 else round(max(values), 2),
        max_loss=None if slope < 0 else round(min(values), 2),
        net_premium=round(
            sum(
                -_signed(leg) * leg.entry_price * leg.quantity
                for leg in legs
                if leg.instrument_type in _OPTION_TYPES
            ),
            2,
        ),
        net_delta=round((today(spot + h) - today(spot - h)) / (2 * h), 2) if priced else None,
    )


def _check(legs: Sequence[PayoffLeg], spot: float, steps: int) -> None:
    if not legs:
        raise PayoffInputError("no legs: add at least one option or future")
    if not spot > 0:
        raise PayoffInputError(f"the underlying's price must be positive, got {spot}")
    if steps < 2:
        raise PayoffInputError(f"at least 2 points, got {steps}")
    for number, leg in enumerate(legs, 1):
        if leg.instrument_type in _OPTION_TYPES:
            if leg.strike is None or leg.strike <= 0:
                raise PayoffInputError(f"leg {number}: an option needs a positive strike")
        elif leg.instrument_type is not InstrumentType.FUT:
            raise PayoffInputError(
                f"leg {number} is {leg.instrument_type}: only options and futures have a payoff"
            )
        if leg.quantity <= 0:
            raise PayoffInputError(f"leg {number}: quantity must be positive, got {leg.quantity}")
        if leg.entry_price < 0:
            raise PayoffInputError(f"leg {number}: price can't be negative")


def _years(legs: Sequence[PayoffLeg], now: datetime) -> float | None:
    """Time left on the options, which must share one expiry: after the
    first expires, the rest are no longer a line at expiry. None: futures only."""
    expiries = sorted({leg.expiry for leg in legs if leg.instrument_type in _OPTION_TYPES})
    if len(expiries) > 1:
        listed = ", ".join(expiry.isoformat() for expiry in expiries)
        raise PayoffInputError(f"options of one expiry only, got {listed}")
    if not expiries:
        return None
    try:
        return years_to_expiry(expiries[0], now)
    except ChainInputError as exc:
        raise PayoffInputError(str(exc)) from exc


def _signed(leg: PayoffLeg) -> int:
    return 1 if leg.side is Side.BUY else -1


def _expiry_value(leg: PayoffLeg, underlying: float) -> float:
    if leg.instrument_type is InstrumentType.FUT:
        worth = underlying
    elif leg.instrument_type is InstrumentType.CE:
        worth = max(underlying - (leg.strike or 0.0), 0.0)
    else:
        worth = max((leg.strike or 0.0) - underlying, 0.0)
    return _signed(leg) * (worth - leg.entry_price) * leg.quantity


def _range(spot: float, span: float, strikes: Sequence[float]) -> tuple[float, float]:
    low, high = spot * (1 - span), spot * (1 + span)
    if strikes and (strikes[0] <= low or strikes[-1] >= high):
        low, high = min(low, strikes[0]), max(high, strikes[-1])
        pad = (high - low) * 0.05
        low, high = low - pad, high + pad
    return max(low, spot * 0.01), high


def _zeros(kinks: Sequence[float], values: Sequence[float], slope: float) -> tuple[float, ...]:
    """Where the line through `values` at `kinks`, going on at `slope` past
    the last, crosses zero. Above zero only."""
    found: list[float] = []
    for (a, fa), (b, fb) in pairwise(zip(kinks, values, strict=True)):
        if fa == 0 and a > 0:
            found.append(a)
        elif fa * fb < 0:
            found.append(a + (b - a) * -fa / (fb - fa))
    last, at_last = kinks[-1], values[-1]
    if at_last == 0 and last > 0:
        found.append(last)
    elif slope and at_last * slope < 0:
        found.append(last - at_last / slope)
    return tuple(sorted({round(x, 2) for x in found if math.isfinite(x)}))
