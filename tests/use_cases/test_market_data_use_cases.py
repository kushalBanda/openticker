from datetime import date

import pytest

from openticker.storage.duckdb import bars_repo
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.get_historical_bars import get_historical_bars
from openticker.use_cases.get_quote import get_quote
from openticker.use_cases.resolve_instrument import UnknownInstrumentError
from tests.fixtures.fake_broker import FAKE_INSTRUMENT, FAKE_LAST_PRICE, FakeBrokerPort


def test_get_quote_resolves_through_instrument_master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])

    quote = get_quote(FakeBrokerPort(), "RELIANCE", "NSE")

    assert quote.instrument == FAKE_INSTRUMENT
    assert quote.last_price == FAKE_LAST_PRICE


def test_get_quote_unknown_symbol_raises_before_calling_broker() -> None:
    with pytest.raises(UnknownInstrumentError, match="sync_instruments"):
        get_quote(FakeBrokerPort(), "RELIANCE", "NSE")


def test_get_historical_bars_stores_what_it_returns() -> None:
    upsert_instruments([FAKE_INSTRUMENT])

    bars = get_historical_bars(
        FakeBrokerPort(), "RELIANCE", "NSE", "day", date(2026, 9, 18), date(2026, 9, 19)
    )

    stored = bars_repo.get_bars(FAKE_INSTRUMENT, "day", date(2026, 9, 18), date(2026, 9, 19))
    assert stored == bars
    assert len(stored) == 2
