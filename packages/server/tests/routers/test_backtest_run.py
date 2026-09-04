from datetime import UTC, datetime
from http import HTTPStatus

from fastapi.testclient import TestClient
from ingest.core.models import Bar
from ingest.storage.duckdb_store import DuckDBStore


def _bar(day: int, close: float) -> Bar:
    return Bar(
        symbol="NSE-RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, day, tzinfo=UTC),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000,
        provider="kite",
    )


def _request_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "strategy_name": "sma_crossover",
        "symbols": ["NSE-RELIANCE"],
        "interval": "1d",
        "from": "2026-01-01T00:00:00Z",
        "to": "2026-01-31T00:00:00Z",
        "starting_cash": 100_000.0,
        "short_window": 2,
        "long_window": 3,
        "quantity": 10,
    }
    body.update(overrides)
    return body


def test_get_strategies_lists_sma_crossover(client: TestClient) -> None:
    resp = client.get("/strategies")
    assert resp.status_code == HTTPStatus.OK
    assert "sma_crossover" in resp.json()["strategy_names"]


def test_run_backtest_no_bars_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post("/backtests", json=_request_body(), headers=auth_headers)
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_run_backtest_returns_generated_run_id(
    client: TestClient, duckdb_store: DuckDBStore, auth_headers: dict[str, str]
) -> None:
    # Dip then recovery forces a short-SMA-crosses-above-long-SMA signal,
    # guaranteeing at least one trade so the run is actually persisted.
    closes = [105.0, 104.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]
    duckdb_store.write_bars(
        [_bar(day, close) for day, close in enumerate(closes, start=1)]
    )

    resp = client.post("/backtests", json=_request_body(), headers=auth_headers)

    assert resp.status_code == HTTPStatus.OK
    body = resp.json()
    assert body.get("run_id")
    assert body["trade_count"] >= 1

    # run_id is server-generated and persisted, listable afterward
    runs = client.get("/backtests", params={"page_size": 100}).json()["run_ids"]
    assert body["run_id"] in runs


def test_run_backtest_bad_strategy_params_returns_422(
    client: TestClient, duckdb_store: DuckDBStore, auth_headers: dict[str, str]
) -> None:
    duckdb_store.write_bars([_bar(day, 100.0 + day) for day in range(1, 10)])

    resp = client.post(
        "/backtests",
        json=_request_body(short_window=5, long_window=2),
        headers=auth_headers,
    )
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_run_backtest_unknown_strategy_returns_422(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/backtests",
        json=_request_body(strategy_name="does_not_exist"),
        headers=auth_headers,
    )
    assert resp.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
