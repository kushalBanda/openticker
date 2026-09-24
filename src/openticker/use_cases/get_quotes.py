"""Quotes for many instruments in one broker call."""

from collections.abc import Sequence
from dataclasses import dataclass

from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import Exchange, Instrument, Quote
from openticker.use_cases.errors import BatchTooLargeError
from openticker.use_cases.resolve_instrument import UnknownInstrumentError, resolve_instrument

# Keeps every answer bounded (ADR 8 in docs/adr).
MAX_QUOTES = 50

NO_QUOTE = "the broker returned no quote (untraded or suspended)"


@dataclass(frozen=True)
class MissingQuote:
    symbol: str
    exchange: str
    reason: str


@dataclass(frozen=True)
class QuotesLookup:
    quotes: list[Quote]  # in the caller's order
    missing: list[MissingQuote]  # unknown first, then unquoted


def get_quotes(broker: BrokerPort, wanted: Sequence[tuple[str, str]]) -> QuotesLookup:
    """`wanted` is (symbol, exchange) pairs; an instrument asked for twice is
    quoted once. One that can't be quoted is listed with the reason; only
    when none of them is known does the call fail."""
    if len(wanted) > MAX_QUOTES:
        raise BatchTooLargeError(f"{len(wanted)} instruments asked for; at most {MAX_QUOTES}")
    known: dict[tuple[Exchange, str], Instrument] = {}
    missing: list[MissingQuote] = []
    first_error: UnknownInstrumentError | None = None
    for symbol, exchange in wanted:
        try:
            instrument = resolve_instrument(symbol, exchange)
        except UnknownInstrumentError as exc:
            first_error = first_error or exc
            missing.append(MissingQuote(symbol, exchange, str(exc)))
            continue
        known.setdefault((instrument.exchange, instrument.symbol), instrument)
    if not known and first_error is not None:
        raise first_error
    quoted = {
        (quote.instrument.exchange, quote.instrument.symbol): quote
        for quote in (broker.get_quotes(list(known.values())) if known else [])
    }
    quotes: list[Quote] = []
    for key, instrument in known.items():
        quote = quoted.get(key)
        if quote is None:
            missing.append(MissingQuote(instrument.symbol, instrument.exchange, NO_QUOTE))
        else:
            quotes.append(quote)
    return QuotesLookup(quotes=quotes, missing=missing)
