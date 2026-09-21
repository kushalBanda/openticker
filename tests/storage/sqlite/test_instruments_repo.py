from dataclasses import replace
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openticker.ports.models import Exchange, Instrument, InstrumentType
from openticker.storage.sqlite import instruments_repo
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import InstrumentRow

_OPTION = Instrument(
    symbol="NIFTY22SEP2623350CE",
    broker_symbol="NIFTY2692223350CE",
    exchange=Exchange.NFO,
    broker_exchange="NFO",
    token="10967554",
    expiry=date(2026, 9, 22),
    strike=23350.0,
    lot_size=65,
    instrument_type=InstrumentType.CE,
    tick_size=0.05,
)

_EQUITY = Instrument(
    symbol="RELIANCE",
    broker_symbol="RELIANCE",
    exchange=Exchange.NSE,
    broker_exchange="NSE",
    token="738561",
    expiry=None,
    strike=None,
    lot_size=1,
    instrument_type=InstrumentType.EQ,
    tick_size=0.05,
)


def _row_count() -> int:
    with Session(get_engine()) as session:
        return session.scalar(select(func.count()).select_from(InstrumentRow)) or 0


def test_upsert_and_get_instrument_round_trips() -> None:
    instruments_repo.upsert_instruments([_OPTION, _EQUITY])

    assert instruments_repo.get_instrument("NIFTY22SEP2623350CE", "NFO") == _OPTION
    assert instruments_repo.get_instrument("RELIANCE", "NSE") == _EQUITY


def test_get_instrument_returns_none_when_absent() -> None:
    assert instruments_repo.get_instrument("RELIANCE", "BSE") is None


def test_instrument_master_upsert_is_idempotent() -> None:
    assert instruments_repo.upsert_instruments([_OPTION, _EQUITY]) == 2
    assert instruments_repo.upsert_instruments([_OPTION, _EQUITY]) == 2

    assert _row_count() == 2


def test_upsert_overwrites_changed_fields() -> None:
    instruments_repo.upsert_instruments([_EQUITY])
    instruments_repo.upsert_instruments([replace(_EQUITY, token="999", lot_size=5)])

    stored = instruments_repo.get_instrument("RELIANCE", "NSE")
    assert stored is not None
    assert stored.token == "999"
    assert stored.lot_size == 5


def test_upsert_empty_list_writes_nothing() -> None:
    assert instruments_repo.upsert_instruments([]) == 0


def test_search_ranks_exact_then_prefix_and_hides_expired() -> None:
    expired = replace(_OPTION, symbol="NIFTY22SEP2523350CE", expiry=date(2025, 9, 22))
    instruments_repo.upsert_instruments([_OPTION, _EQUITY, expired])

    found = instruments_repo.search_instruments(
        "nifty", exchange=None, instrument_type=None, live_on=date(2026, 9, 21), limit=10
    )

    assert [instrument.symbol for instrument in found] == ["NIFTY22SEP2623350CE"]


def test_search_treats_like_wildcards_literally() -> None:
    instruments_repo.upsert_instruments([_EQUITY])

    assert instruments_repo.search_instruments(
        "%", exchange=None, instrument_type=None, live_on=None, limit=10
    ) == []
