from datetime import UTC, datetime
from pathlib import Path

from strategy.storage.run_store import RunMetadata, RunStore


def _run(run_id: str = "run-1", strategy: str = "sma_cross") -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        strategy=strategy,
        params={"long_window": 20, "quantity": 10},
        symbols=["RELIANCE"],
        interval="1d",
        starting_cash=100_000.0,
    )


def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    store = RunStore(db_path=tmp_path / "test.duckdb")
    store.write_run(_run())
    store.ensure_schema()
    assert store.get_run("run-1") is not None


def test_write_then_get_round_trips(tmp_path: Path) -> None:
    store = RunStore(db_path=tmp_path / "test.duckdb")
    run = _run()

    store.write_run(run)
    result = store.get_run("run-1")

    assert result == run


def test_get_run_returns_none_when_missing(tmp_path: Path) -> None:
    store = RunStore(db_path=tmp_path / "test.duckdb")

    assert store.get_run("does-not-exist") is None


def test_get_most_recent_run_returns_latest_by_created_at(tmp_path: Path) -> None:
    store = RunStore(db_path=tmp_path / "test.duckdb")
    older = RunMetadata(
        run_id="run-old",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        strategy="sma_cross",
        params={},
        symbols=["RELIANCE"],
        interval="1d",
        starting_cash=100_000.0,
    )
    newer = RunMetadata(
        run_id="run-new",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        strategy="buy_and_hold",
        params={},
        symbols=["TCS"],
        interval="1d",
        starting_cash=50_000.0,
    )

    store.write_run(older)
    store.write_run(newer)

    assert store.get_most_recent_run() == newer


def test_get_most_recent_run_returns_none_when_empty(tmp_path: Path) -> None:
    store = RunStore(db_path=tmp_path / "test.duckdb")

    assert store.get_most_recent_run() is None


def test_write_run_is_idempotent_on_rerun(tmp_path: Path) -> None:
    store = RunStore(db_path=tmp_path / "test.duckdb")
    run = _run()

    store.write_run(run)
    store.write_run(run)

    assert store.get_run("run-1") == run
