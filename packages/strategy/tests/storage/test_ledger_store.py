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


def test_write_entries_is_idempotent_on_rerun(tmp_path: Path) -> None:
    store = LedgerStore(db_path=tmp_path / "test.duckdb")
    entries = [_entry(0), _entry(1)]

    store.write_entries("run-1", entries)
    store.write_entries("run-1", entries)  # re-run under the same run_id

    result = store.query_entries("run-1")
    assert len(result) == 2  # not duplicated
