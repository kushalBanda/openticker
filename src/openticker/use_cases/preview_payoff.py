"""Legs as asked for -> contracts, prices and volatilities -> their payoff
(ADR 38 in docs/adr). Nothing is placed."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from openticker.core.options.chain import ChainInputError, years_to_expiry
from openticker.core.options.greeks import implied_volatility
from openticker.core.options.payoff import Payoff, PayoffInputError, PayoffLeg, payoff
from openticker.core.options.underlyings import underlying_of
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import Exchange, Instrument, InstrumentType, Side
from openticker.use_cases.errors import BatchTooLargeError
from openticker.use_cases.resolve_instrument import resolve_instrument

# Keeps every answer bounded (ADR 8 in docs/adr).
MAX_PAYOFF_LEGS = 20


class MixedUnderlyingsError(ValueError):
    """The legs are written on more than one underlying, or on none OpenTicker knows."""


@dataclass(frozen=True)
class PayoffLegRequest:
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int
    price: float | None  # None: the leg's last price


@dataclass(frozen=True)
class PricedLeg:
    instrument: Instrument
    side: Side
    quantity: int
    price: float  # the price the payoff assumes
    implied_volatility: float | None  # a fraction; None for a future or an unpriced option


@dataclass(frozen=True)
class PayoffPreview:
    underlying: Instrument
    spot: float
    legs: tuple[PricedLeg, ...]
    payoff: Payoff


def preview_payoff(
    legs: Sequence[PayoffLegRequest], broker: BrokerPort, now: datetime, rate: float = 0.0
) -> PayoffPreview:
    """Every leg a future or an option on one underlying. A leg without a
    price assumes its last price; each option's volatility comes from its
    last price, solved on the underlying as the payoff prices it."""
    if not legs:
        raise PayoffInputError("no legs: add at least one option or future")
    if len(legs) > MAX_PAYOFF_LEGS:
        raise BatchTooLargeError(f"{len(legs)} legs; at most {MAX_PAYOFF_LEGS}")
    instruments = [resolve_instrument(leg.symbol, leg.exchange.value) for leg in legs]
    written_on = set()
    for instrument in instruments:
        if instrument.instrument_type not in (
            InstrumentType.CE,
            InstrumentType.PE,
            InstrumentType.FUT,
        ):
            raise PayoffInputError(
                f"{instrument.symbol} is {instrument.instrument_type}: "
                "only options and futures have a payoff"
            )
        found = underlying_of(instrument)
        if found is None:
            raise MixedUnderlyingsError(f"no known underlying for {instrument.symbol}")
        written_on.add(found)
    if len(written_on) > 1:
        names = ", ".join(sorted(symbol for symbol, _ in written_on))
        raise MixedUnderlyingsError(f"legs on one underlying only, got {names}")
    ((symbol, exchange),) = written_on
    underlying = resolve_instrument(symbol, exchange.value)

    quotes = {
        quote.instrument.symbol: quote for quote in broker.get_quotes([underlying, *instruments])
    }
    spot = quotes[underlying.symbol].last_price if underlying.symbol in quotes else 0.0
    if spot <= 0:
        raise BrokerError(
            f"no usable price for {underlying.symbol} yet; try again once it has traded"
        )

    priced: list[PricedLeg] = []
    for leg, instrument in zip(legs, instruments, strict=True):
        quote = quotes.get(instrument.symbol)
        last = quote.last_price if quote is not None and quote.last_price > 0 else None
        price = leg.price if leg.price is not None else last
        if price is None:
            raise BrokerError(f"no price for {instrument.symbol} yet; give the leg a price")
        priced.append(
            PricedLeg(
                instrument,
                leg.side,
                leg.quantity,
                price,
                _volatility(instrument, last, spot, now, rate),
            )
        )

    result = payoff(
        [
            PayoffLeg(
                instrument_type=leg.instrument.instrument_type,
                strike=leg.instrument.strike,
                expiry=leg.instrument.expiry or now.date(),
                side=leg.side,
                quantity=leg.quantity,
                entry_price=leg.price,
            )
            for leg in priced
        ],
        spot,
        now,
        {index: leg.implied_volatility for index, leg in enumerate(priced)},
        rate,
    )
    return PayoffPreview(underlying, spot, tuple(priced), result)


def _volatility(
    instrument: Instrument, last: float | None, spot: float, now: datetime, rate: float
) -> float | None:
    if instrument.instrument_type is InstrumentType.FUT or last is None:
        return None
    assert instrument.expiry is not None and instrument.strike is not None
    try:
        years = years_to_expiry(instrument.expiry, now)
    except ChainInputError as exc:
        raise PayoffInputError(str(exc)) from exc
    return implied_volatility(
        instrument.instrument_type, last, spot, instrument.strike, years, rate
    )
