"""Which options belong to which underlying.

Option symbols are built from the contract's underlying name (ADR 4 in
docs/adr): `NIFTY22SEP2623350CE`. For a stock that name is its own symbol;
an index is listed under a different name than its options use, so indices
are mapped explicitly.
"""

from openticker.ports.models import Exchange, Instrument, InstrumentType

INDEX_OPTION_NAMES: dict[tuple[str, Exchange], str] = {
    ("NIFTY 50", Exchange.NSE): "NIFTY",
    ("NIFTY BANK", Exchange.NSE): "BANKNIFTY",
    ("NIFTY FIN SERVICE", Exchange.NSE): "FINNIFTY",
    ("NIFTY MID SELECT", Exchange.NSE): "MIDCPNIFTY",
    ("NIFTY NEXT 50", Exchange.NSE): "NIFTYNXT50",
    ("SENSEX", Exchange.BSE): "SENSEX",
    ("BANKEX", Exchange.BSE): "BANKEX",
}

_OPTIONS_EXCHANGE = {Exchange.NSE: Exchange.NFO, Exchange.BSE: Exchange.BFO}


class UnsupportedUnderlyingError(LookupError):
    """The instrument has no listed options OpenTicker knows how to find."""


def options_of(underlying: Instrument) -> tuple[str, Exchange]:
    """The name its option symbols start with, and the exchange they trade on."""
    options_exchange = _OPTIONS_EXCHANGE.get(underlying.exchange)
    if options_exchange is None:
        raise UnsupportedUnderlyingError(
            f"options on {underlying.exchange} underlyings are not supported; "
            "use an NSE or BSE index or stock"
        )
    if underlying.instrument_type is InstrumentType.INDEX:
        name = INDEX_OPTION_NAMES.get((underlying.symbol, underlying.exchange))
        if name is None:
            supported = ", ".join(sorted(symbol for symbol, _ in INDEX_OPTION_NAMES))
            raise UnsupportedUnderlyingError(
                f"no options listed for index {underlying.symbol!r}; indices with options: "
                f"{supported}"
            )
        return name, options_exchange
    if underlying.instrument_type is InstrumentType.EQ:
        return underlying.symbol, options_exchange
    raise UnsupportedUnderlyingError(
        f"{underlying.symbol} is {underlying.instrument_type}; an option chain needs an index "
        "or a stock as its underlying"
    )
