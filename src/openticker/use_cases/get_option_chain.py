"""Underlying -> its listed options for one expiry -> live quotes -> chain with Greeks."""

from datetime import date, datetime

from openticker.core.options.chain import (
    atm_strike,
    build_option_chain,
    expires_at,
    strikes_around,
)
from openticker.core.options.models import OptionChain
from openticker.core.options.underlyings import options_of
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage.sqlite.instruments_repo import option_contracts, option_expiries
from openticker.use_cases.resolve_instrument import resolve_instrument


class NoOptionsError(LookupError):
    """The underlying has no unexpired options in the local instrument master,
    or none for the requested expiry."""


def get_option_chain(
    broker: BrokerPort,
    symbol: str,
    exchange: str,
    expiry: date | None,
    strike_count: int,
    rate: float,
    now: datetime,
) -> tuple[OptionChain, list[date]]:
    """The chain for `expiry` (nearest unexpired when None), `strike_count`
    strikes either side of at-the-money, plus every unexpired expiry."""
    underlying = resolve_instrument(symbol, exchange)
    name, options_exchange = options_of(underlying)
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    expiries = [
        listed
        for listed in option_expiries(name, options_exchange, today)
        if expires_at(listed) > now
    ]
    if not expiries:
        raise NoOptionsError(
            f"no unexpired {name} options on {options_exchange} in the instrument master; "
            "run sync_instruments"
        )
    chosen = expiry or expiries[0]
    if chosen not in expiries:
        raise NoOptionsError(
            f"no unexpired {name} options expiring {chosen}; available: "
            f"{', '.join(listed.isoformat() for listed in expiries[:8])}"
        )

    contracts = option_contracts(name, options_exchange, chosen)
    underlying_price = broker.get_quote(underlying).last_price
    if underlying_price <= 0:
        raise BrokerError(f"no usable price for {symbol} yet; try again once it has traded")
    strikes = sorted({contract.strike for contract in contracts if contract.strike is not None})
    shown_strikes = set(
        strikes_around(atm_strike(underlying_price, strikes), strikes, strike_count)
    )
    shown = [contract for contract in contracts if contract.strike in shown_strikes]
    quotes = {quote.instrument.symbol: quote for quote in broker.get_quotes(shown)}
    chain = build_option_chain(underlying, underlying_price, shown, quotes, now, rate)
    return chain, expiries
