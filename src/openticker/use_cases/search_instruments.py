"""Find instruments in the local instrument master by symbol fragment."""

from datetime import date

from openticker.ports.models import Exchange, Instrument, InstrumentType
from openticker.storage.sqlite.instruments_repo import search_instruments as search_repo


def search_instruments(
    query: str,
    exchange: Exchange | None,
    instrument_type: InstrumentType | None,
    include_expired: bool,
    today: date,
    limit: int,
) -> list[Instrument]:
    return search_repo(
        query,
        exchange.value if exchange is not None else None,
        instrument_type.value if instrument_type is not None else None,
        live_on=None if include_expired else today,
        limit=limit,
    )
