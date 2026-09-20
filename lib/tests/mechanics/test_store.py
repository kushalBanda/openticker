from datetime import UTC, datetime
from pathlib import Path

from lib.mechanics.models import Bar
from lib.mechanics.store import DuckDBStore


def _bar(ts: datetime, close: float) -> Bar:
    return Bar(
        symbol="RELIANCE",
        interval="1d",
        ts=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        provider="kite",
    )


def test_write_and_query_round_trip(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "test.duckdb")
    bars = [
        _bar(datetime(2026, 1, 1, tzinfo=UTC), 100.0),
        _bar(datetime(2026, 1, 2, tzinfo=UTC), 101.0),
    ]
    store.write_bars(bars)
    result = store.query_bars(
        "RELIANCE", "1d", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC)
    )
    assert [b.close for b in result] == [100.0, 101.0]


def test_find_missing_range_full_gap_when_empty(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "test.duckdb")
    frm, to = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 5, tzinfo=UTC)
    assert store.find_missing_range("RELIANCE", "1d", frm, to) == [(frm, to)]


def test_find_missing_range_empty_when_fully_cached(tmp_path: Path) -> None:
    store = DuckDBStore(tmp_path / "test.duckdb")
    store.write_bars([_bar(datetime(2026, 1, 2, tzinfo=UTC), 100.0)])
    gaps = store.find_missing_range(
        "RELIANCE", "1d", datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
    )
    assert gaps == []
