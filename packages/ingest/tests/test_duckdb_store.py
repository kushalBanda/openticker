from datetime import UTC, datetime, timedelta
from pathlib import Path

from ingest.core.models import Bar, IndexConstituent
from ingest.storage.duckdb_store import DuckDBStore


def make_bar(day: int, close: float = 100.0) -> Bar:
    return Bar(
        symbol="RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, day, tzinfo=UTC),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100,
        provider="fake",
    )


def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    store = DuckDBStore(db_path=tmp_path / "test.duckdb")
    store.write_bars([make_bar(2)])
    store.ensure_schema()
    result = store.query_bars(
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert len(result) == 1


def test_find_missing_range_empty_store(tmp_path: Path) -> None:
    store = DuckDBStore(db_path=tmp_path / "test.duckdb")
    gaps = store.find_missing_range(
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert gaps == [
        (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 5, tzinfo=UTC))
    ]


def test_find_missing_range_full_hit(tmp_path: Path) -> None:
    store = DuckDBStore(db_path=tmp_path / "test.duckdb")
    store.write_bars([make_bar(1), make_bar(2), make_bar(3)])
    gaps = store.find_missing_range(
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert gaps == []


def test_find_missing_range_trailing_gap(tmp_path: Path) -> None:
    store = DuckDBStore(db_path=tmp_path / "test.duckdb")
    store.write_bars([make_bar(1), make_bar(2)])
    gaps = store.find_missing_range(
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert gaps == [
        (
            datetime(2026, 1, 2, tzinfo=UTC) + timedelta(microseconds=1),
            datetime(2026, 1, 5, tzinfo=UTC),
        )
    ]


def test_find_missing_range_leading_gap(tmp_path: Path) -> None:
    store = DuckDBStore(db_path=tmp_path / "test.duckdb")
    store.write_bars([make_bar(4), make_bar(5)])
    gaps = store.find_missing_range(
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert gaps == [
        (
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 4, tzinfo=UTC) - timedelta(microseconds=1),
        )
    ]


def test_find_missing_range_leading_and_trailing_gap(tmp_path: Path) -> None:
    store = DuckDBStore(db_path=tmp_path / "test.duckdb")
    store.write_bars([make_bar(3)])
    gaps = store.find_missing_range(
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 5, tzinfo=UTC),
    )
    assert len(gaps) == 2
    assert gaps[0] == (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 3, tzinfo=UTC) - timedelta(microseconds=1),
    )
    assert gaps[1] == (
        datetime(2026, 1, 3, tzinfo=UTC) + timedelta(microseconds=1),
        datetime(2026, 1, 5, tzinfo=UTC),
    )


def test_write_and_query_index_constituents(tmp_path: Path) -> None:
    store = DuckDBStore(db_path=tmp_path / "test.duckdb")
    store.write_index_constituents(
        [
            IndexConstituent(
                index_name="NIFTY50", symbol="RELIANCE", year=2026, source="manual"
            ),
            IndexConstituent(
                index_name="NIFTY50", symbol="TCS", year=2026, source="manual"
            ),
        ]
    )
    symbols = store.query_index_constituents("NIFTY50", 2026)
    assert symbols == ["RELIANCE", "TCS"]


def test_query_index_constituents_empty_for_unknown_year(tmp_path: Path) -> None:
    store = DuckDBStore(db_path=tmp_path / "test.duckdb")
    store.write_index_constituents(
        [
            IndexConstituent(
                index_name="NIFTY50", symbol="RELIANCE", year=2026, source="manual"
            )
        ]
    )
    assert store.query_index_constituents("NIFTY50", 2020) == []


def test_write_index_constituents_upserts_same_year(tmp_path: Path) -> None:
    store = DuckDBStore(db_path=tmp_path / "test.duckdb")
    store.write_index_constituents(
        [
            IndexConstituent(
                index_name="NIFTY50", symbol="RELIANCE", year=2026, source="manual"
            )
        ]
    )
    store.write_index_constituents(
        [
            IndexConstituent(
                index_name="NIFTY50", symbol="RELIANCE", year=2026, source="nse_csv"
            )
        ]
    )
    assert store.query_index_constituents("NIFTY50", 2026) == ["RELIANCE"]
