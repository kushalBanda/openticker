from datetime import UTC, datetime
from pathlib import Path

from strategy.storage.equity_curve_store import EquityCurveStore


def _curve(sequence_hint: int = 0) -> list[tuple[datetime, float]]:
    return [
        (datetime(2026, 1, 1 + i, tzinfo=UTC), 100_000.0 + i)
        for i in range(sequence_hint, sequence_hint + 2)
    ]


def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    store = EquityCurveStore(db_path=tmp_path / "test.duckdb")
    store.write_points("run-1", _curve())
    store.ensure_schema()
    result = store.query_points("run-1")
    assert len(result) == 2


def test_write_then_query_round_trips(tmp_path: Path) -> None:
    store = EquityCurveStore(db_path=tmp_path / "test.duckdb")
    curve = [
        (datetime(2026, 1, 1, tzinfo=UTC), 100_000.0),
        (datetime(2026, 1, 2, tzinfo=UTC), 100_500.0),
    ]

    store.write_points("run-1", curve)
    result = store.query_points("run-1")

    assert len(result) == 2
    assert result[0][1] == 100_000.0
    assert result[1][1] == 100_500.0
    assert result[0][0] < result[1][0]  # sequence order preserved


def test_isolates_by_run_id(tmp_path: Path) -> None:
    store = EquityCurveStore(db_path=tmp_path / "test.duckdb")
    store.write_points("run-1", _curve())
    store.write_points("run-2", _curve() + _curve(2))

    assert len(store.query_points("run-1")) == 2
    assert len(store.query_points("run-2")) == 4


def test_write_points_empty_list_is_a_noop(tmp_path: Path) -> None:
    store = EquityCurveStore(db_path=tmp_path / "test.duckdb")

    store.write_points("run-1", [])

    assert store.query_points("run-1") == []


def test_write_points_is_idempotent_on_rerun(tmp_path: Path) -> None:
    store = EquityCurveStore(db_path=tmp_path / "test.duckdb")
    curve = _curve()

    store.write_points("run-1", curve)
    store.write_points("run-1", curve)  # re-run under the same run_id

    result = store.query_points("run-1")
    assert len(result) == 2  # not duplicated
