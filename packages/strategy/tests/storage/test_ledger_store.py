from datetime import UTC, datetime
from pathlib import Path

from strategy.core.ledger import LedgerEntry
from strategy.storage.ledger_store import LedgerStore


def _entry(sequence_hint: int = 0, symbol: str = "NSE-RELIANCE") -> LedgerEntry:
    return LedgerEntry(
        symbol=symbol,
        side="buy",
        quantity=10,
        fill_price=100.0 + sequence_hint,
        fill_ts=datetime(2026, 1, 1 + sequence_hint, tzinfo=UTC),
        commission=1.0,
        cost_basis_before=0.0,
        realized_pnl=0.0,
        cash_after=9_000.0,
        position_after=10,
    )


def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    store = LedgerStore(db_path=tmp_path / "test.duckdb")
    store.write_entries("run-1", [_entry()])
    store.ensure_schema()
    result = store.query_entries("run-1")
    assert len(result) == 1


def test_write_then_query_round_trips(tmp_path: Path) -> None:
    store = LedgerStore(db_path=tmp_path / "test.duckdb")
    entries = [_entry(0), _entry(1)]

    store.write_entries("run-1", entries)
    result = store.query_entries("run-1")

    assert len(result) == 2
    assert result[0].symbol == "NSE-RELIANCE"
    assert result[0].fill_price == 100.0
    assert result[1].fill_price == 101.0
    assert result[0].fill_ts < result[1].fill_ts  # sequence order preserved


def test_isolates_by_run_id(tmp_path: Path) -> None:
    store = LedgerStore(db_path=tmp_path / "test.duckdb")
    store.write_entries("run-1", [_entry(0)])
    store.write_entries("run-2", [_entry(0), _entry(1)])

    assert len(store.query_entries("run-1")) == 1
    assert len(store.query_entries("run-2")) == 2


def test_write_entries_empty_list_is_a_noop(tmp_path: Path) -> None:
    store = LedgerStore(db_path=tmp_path / "test.duckdb")

    store.write_entries("run-1", [])

    assert store.query_entries("run-1") == []


def test_list_run_ids_returns_distinct_sorted(tmp_path: Path) -> None:
    store = LedgerStore(db_path=tmp_path / "test.duckdb")
    store.write_entries("run-2", [_entry(0)])
    store.write_entries("run-1", [_entry(0)])

    assert store.list_run_ids() == ["run-1", "run-2"]


def test_list_run_ids_empty_store(tmp_path: Path) -> None:
    store = LedgerStore(db_path=tmp_path / "test.duckdb")

    assert store.list_run_ids() == []


def test_list_run_ids_supports_limit_offset(tmp_path: Path) -> None:
    store = LedgerStore(db_path=tmp_path / "test.duckdb")
    for i in range(3):
        store.write_entries(f"run-{i}", [_entry(0)])

    assert store.list_run_ids(limit=2, offset=0) == ["run-0", "run-1"]
    assert store.list_run_ids(limit=2, offset=2) == ["run-2"]
    assert store.count_run_ids() == 3


def test_query_entries_supports_limit_offset(tmp_path: Path) -> None:
    store = LedgerStore(db_path=tmp_path / "test.duckdb")
    store.write_entries("run-1", [_entry(0), _entry(1), _entry(2)])

    page1 = store.query_entries("run-1", limit=2, offset=0)
    page2 = store.query_entries("run-1", limit=2, offset=2)

    assert [e.fill_price for e in page1] == [100.0, 101.0]
    assert [e.fill_price for e in page2] == [102.0]
    assert store.count_entries("run-1") == 3


def test_write_entries_is_idempotent_on_rerun(tmp_path: Path) -> None:
    store = LedgerStore(db_path=tmp_path / "test.duckdb")
    entries = [_entry(0), _entry(1)]

    store.write_entries("run-1", entries)
    store.write_entries("run-1", entries)  # re-run under the same run_id

    result = store.query_entries("run-1")
    assert len(result) == 2  # not duplicated
