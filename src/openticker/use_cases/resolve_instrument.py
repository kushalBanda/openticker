"""Standardized (symbol, exchange) -> Instrument, via the synced instrument master.
Shared by every use case that takes a symbol from a caller (quotes, bars, and
later orders)."""

from openticker.ports.models import Instrument
from openticker.storage.sqlite.instruments_repo import get_instrument


class UnknownInstrumentError(LookupError):
    """No instrument with this symbol on this exchange in the local instrument master."""


def resolve_instrument(symbol: str, exchange: str) -> Instrument:
    instrument = get_instrument(symbol, exchange)
    if instrument is None:
        raise UnknownInstrumentError(
            f"no instrument {symbol!r} on {exchange!r} — check the symbol, or run "
            "sync_instruments if the instrument master is empty or stale"
        )
    return instrument
