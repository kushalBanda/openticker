"""Option chain assembly. Pure: contracts, prices and the clock are passed in.

Conventions (ADR 16 in docs/adr): options expire at 15:30 exchange time; the
at-the-money strike is the listed strike nearest the underlying's price (ties
go to the lower strike); the forward comes from put-call parity at that strike
and falls back to the underlying's price when either leg is unpriced.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time

from openticker.core.options.greeks import MIN_YEARS_TO_EXPIRY, greeks
from openticker.core.options.models import ChainRow, OptionChain, OptionQuote
from openticker.ports.models import EXCHANGE_TIMEZONE, Instrument, InstrumentType, Quote

EXPIRY_TIME = time(15, 30)
_SECONDS_PER_YEAR = 365.0 * 24 * 60 * 60
_OPTION_TYPES = (InstrumentType.CE, InstrumentType.PE)


class ChainInputError(ValueError):
    """Contracts are missing, of mixed expiries, or already expired."""


def expires_at(expiry: date) -> datetime:
    return datetime.combine(expiry, EXPIRY_TIME, tzinfo=EXCHANGE_TIMEZONE).astimezone(UTC)


def years_to_expiry(expiry: date, now: datetime) -> float:
    """Calendar time left, floored at `MIN_YEARS_TO_EXPIRY`. Raises once expired."""
    seconds = (expires_at(expiry) - now).total_seconds()
    if seconds <= 0:
        raise ChainInputError(f"options expiring {expiry} have already expired")
    return max(seconds / _SECONDS_PER_YEAR, MIN_YEARS_TO_EXPIRY)


def atm_strike(underlying_price: float, strikes: Sequence[float]) -> float:
    if not strikes:
        raise ChainInputError("no strikes to choose an at-the-money strike from")
    return min(strikes, key=lambda strike: (abs(strike - underlying_price), strike))


def strike_label(
    option_type: InstrumentType, strike: float, atm: float, strikes: Sequence[float]
) -> str:
    """ATM, or ITM<n>/OTM<n> counted in listed strikes from the ATM strike.
    Below ATM a call is in the money and a put out of it; above, the reverse."""
    ordered = sorted(strikes)
    steps = ordered.index(strike) - ordered.index(atm)
    if steps == 0:
        return "ATM"
    in_the_money = steps < 0 if option_type is InstrumentType.CE else steps > 0
    return f"{'ITM' if in_the_money else 'OTM'}{abs(steps)}"


def strikes_around(atm: float, strikes: Sequence[float], count: int) -> list[float]:
    """The ATM strike and up to `count` listed strikes either side of it."""
    ordered = sorted(set(strikes))
    center = ordered.index(atm)
    return ordered[max(0, center - count) : center + count + 1]


def forward_price(
    atm: float,
    call_price: float | None,
    put_price: float | None,
    years: float,
    rate: float,
    fallback: float,
) -> float:
    """F = K + (C - P) * e^(rT). Index futures trade above spot, so pricing off
    spot would skew every delta; the ATM pair gives the forward for free."""
    if call_price and put_price:
        forward = atm + (call_price - put_price) * math.exp(rate * years)
        if forward > 0:
            return forward
    return fallback


def build_option_chain(
    underlying: Instrument,
    underlying_price: float,
    contracts: Sequence[Instrument],
    quotes: Mapping[str, Quote],
    now: datetime,
    rate: float = 0.0,
) -> OptionChain:
    """One expiry's chain. `contracts` are that expiry's calls and puts to show;
    `quotes` is keyed by symbol, and a contract without one (or priced at zero)
    appears with no price and no Greeks."""
    if not contracts:
        raise ChainInputError(f"no option contracts given for {underlying.symbol}")
    expiries = {contract.expiry for contract in contracts if contract.expiry is not None}
    if len(expiries) != 1 or any(contract.expiry is None for contract in contracts):
        raise ChainInputError(f"contracts must share one expiry, got {sorted(map(str, expiries))}")
    (expiry,) = expiries
    years = years_to_expiry(expiry, now)

    by_strike: dict[float, dict[InstrumentType, Instrument]] = {}
    for contract in contracts:
        if contract.strike is None or contract.instrument_type not in _OPTION_TYPES:
            raise ChainInputError(f"{contract.symbol} is not an option with a strike")
        by_strike.setdefault(contract.strike, {})[contract.instrument_type] = contract
    strikes = sorted(by_strike)
    atm = atm_strike(underlying_price, strikes)

    def price_of(contract: Instrument | None) -> float | None:
        quote = quotes.get(contract.symbol) if contract is not None else None
        return quote.last_price if quote is not None and quote.last_price > 0 else None

    forward = forward_price(
        atm,
        price_of(by_strike[atm].get(InstrumentType.CE)),
        price_of(by_strike[atm].get(InstrumentType.PE)),
        years,
        rate,
        fallback=underlying_price,
    )

    def option_quote(strike: float, option_type: InstrumentType) -> OptionQuote | None:
        contract = by_strike[strike].get(option_type)
        if contract is None:
            return None
        price = price_of(contract)
        quote = quotes.get(contract.symbol)
        return OptionQuote(
            instrument=contract,
            label=strike_label(option_type, strike, atm, strikes),
            last_price=price,
            open_interest=quote.open_interest if quote is not None else None,
            greeks=(
                greeks(option_type, price, forward, strike, years, rate)
                if price is not None
                else None
            ),
        )

    return OptionChain(
        underlying=underlying,
        underlying_price=underlying_price,
        forward_price=forward,
        expiry=expiry,
        expires_at=expires_at(expiry),
        atm_strike=atm,
        interest_rate=rate,
        rows=tuple(
            ChainRow(
                strike=strike,
                call=option_quote(strike, InstrumentType.CE),
                put=option_quote(strike, InstrumentType.PE),
            )
            for strike in strikes
        ),
    )
