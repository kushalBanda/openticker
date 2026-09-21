from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from openticker.ports.models import Bar
from openticker.storage.duckdb import bars_repo
from tests.fixtures.fake_broker import FAKE_INSTRUMENT


def _bar(timestamp: datetime, close: float = 100.0) -> Bar:
    return Bar(
        instrument=FAKE_INSTRUMENT,
        interval="day",
        open=99.0,
        high=101.0,
        low=98.0,
        close=close,
        volume=1000,
        timestamp=timestamp,
    )


# Daily candles for 17 and 18 Sep 2026, as Kite stamps them: 00:00 IST.
_SEP_17 = datetime(2026, 9, 16, 18, 30, tzinfo=UTC)
_SEP_18 = datetime(2026, 9, 17, 18, 30, tzinfo=UTC)


def test_write_and_get_bars_round_trips() -> None:
    bars_repo.write_bars([_bar(_SEP_17), _bar(_SEP_18)])

    stored = bars_repo.get_bars(FAKE_INSTRUMENT, "day", date(2026, 9, 17), date(2026, 9, 18))

    assert stored == [_bar(_SEP_17), _bar(_SEP_18)]


def test_get_bars_filters_on_exchange_local_trading_dates() -> None:
    bars_repo.write_bars([_bar(_SEP_17), _bar(_SEP_18)])

    # 18 Sep's candle is 17 Sep in UTC — it must still come back for an 18 Sep query.
    stored = bars_repo.get_bars(FAKE_INSTRUMENT, "day", date(2026, 9, 18), date(2026, 9, 18))

    assert [bar.timestamp for bar in stored] == [_SEP_18]


def test_get_bars_returns_empty_not_error_for_no_data() -> None:
    assert bars_repo.get_bars(FAKE_INSTRUMENT, "day", date(2026, 1, 1), date(2026, 12, 31)) == []


def test_rewriting_a_range_overwrites_not_duplicates() -> None:
    bars_repo.write_bars([_bar(_SEP_17, close=100.0)])
    bars_repo.write_bars([_bar(_SEP_17, close=105.0)])

    stored = bars_repo.get_bars(FAKE_INSTRUMENT, "day", date(2026, 9, 17), date(2026, 9, 17))

    assert [bar.close for bar in stored] == [105.0]


def test_write_bars_fails_loud_on_partial_range() -> None:
    bad = replace(_bar(_SEP_18), timestamp=datetime(2026, 9, 18))  # noqa: DTZ001 — naive on purpose

    with pytest.raises(bars_repo.InvalidBarsError):
        bars_repo.write_bars([_bar(_SEP_17), bad])

    assert bars_repo.get_bars(FAKE_INSTRUMENT, "day", date(2026, 9, 1), date(2026, 9, 30)) == []
