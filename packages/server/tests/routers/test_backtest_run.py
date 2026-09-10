from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from agents.advisors.pairs_trading.schema import (
    PairsTradingProposal,
    SelectedPairWeight,
)
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
        "strategy_name": "sma_cross",
        "symbols": ["NSE-RELIANCE"],
        "interval": "1d",
        "from": "2026-01-01T00:00:00Z",
        "to": "2026-01-31T00:00:00Z",
        "starting_cash": 100_000.0,
        "long_window": 3,
        "quantity": 10,
    }
    body.update(overrides)
    return body


def test_get_strategies_lists_sma_cross(client: TestClient) -> None:
    resp = client.get("/strategies")
    assert resp.status_code == HTTPStatus.OK
    assert "sma_cross" in resp.json()["strategy_names"]


def test_run_backtest_no_bars_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.post("/backtests", json=_request_body(), headers=auth_headers)
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_run_backtest_returns_generated_run_id(
    client: TestClient, duckdb_store: DuckDBStore, auth_headers: dict[str, str]
) -> None:
    # Dip then recovery forces a price-crosses-above-trend-SMA signal,
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

    body = _request_body()
    del body["long_window"]
    resp = client.post("/backtests", json=body, headers=auth_headers)
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


def test_run_backtest_buy_and_hold_routes_through_discriminated_union(
    client: TestClient, duckdb_store: DuckDBStore, auth_headers: dict[str, str]
) -> None:
    duckdb_store.write_bars([_bar(day, 100.0 + day) for day in range(1, 5)])

    body = {
        "strategy_name": "buy_and_hold",
        "symbols": ["NSE-RELIANCE"],
        "interval": "1d",
        "from": "2026-01-01T00:00:00Z",
        "to": "2026-01-31T00:00:00Z",
        "starting_cash": 100_000.0,
        "quantity": 10,
    }
    resp = client.post("/backtests", json=body, headers=auth_headers)

    assert resp.status_code == HTTPStatus.OK
    assert resp.json()["trade_count"] == 1


def test_run_backtest_time_series_momentum_routes_through_discriminated_union(
    client: TestClient, duckdb_store: DuckDBStore, auth_headers: dict[str, str]
) -> None:
    # Flat then a sharp rise forces a positive trailing-return signal on
    # the last-but-one bar, filling on the final bar.
    closes = [100.0] * 5 + [150.0, 150.0]
    duckdb_store.write_bars(
        [_bar(day, close) for day, close in enumerate(closes, start=1)]
    )

    body = {
        "strategy_name": "time_series_momentum",
        "symbols": ["NSE-RELIANCE"],
        "interval": "1d",
        "from": "2026-01-01T00:00:00Z",
        "to": "2026-01-31T00:00:00Z",
        "starting_cash": 100_000.0,
        "window": 5,
        "target_risk_pct": 0.02,
        "vol_window": 3,
    }
    resp = client.post("/backtests", json=body, headers=auth_headers)

    assert resp.status_code == HTTPStatus.OK
    assert resp.json()["trade_count"] >= 1


def _pair_bar(symbol: str, day: int, close: float) -> Bar:
    ts = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return Bar(
        symbol=symbol,
        interval="1d",
        ts=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        provider="kite",
    )


def test_run_backtest_pairs_trading_routes_through_discriminated_union(
    client: TestClient, duckdb_store: DuckDBStore, auth_headers: dict[str, str]
) -> None:
    # Tight lockstep for a month (formation), then one leg crashes — enough
    # to force a reformation and a real entry, proving the request actually
    # reaches PairsTradingStrategy end to end, not just that the schema
    # validates.
    def a_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 101.0

    def b_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 100.9

    formation_days = range(32)
    bars = [_pair_bar("NSE-RELIANCE", d, a_close(d)) for d in formation_days]
    bars += [_pair_bar("NSE-TCS", d, b_close(d)) for d in formation_days]
    bars += [_pair_bar("NSE-RELIANCE", d, 100.0) for d in (32, 33)]
    bars += [_pair_bar("NSE-TCS", d, 1.0) for d in (32, 33)]
    duckdb_store.write_bars(bars)

    body = {
        "strategy_name": "pairs_trading",
        "symbols": ["NSE-RELIANCE", "NSE-TCS"],
        "interval": "1d",
        "from": "2026-01-01T00:00:00Z",
        "to": "2026-03-01T00:00:00Z",
        "starting_cash": 100_000.0,
        "formation_months": 1,
        "trading_months": 1,
        "top_n_pairs": 1,
        "entry_z": 2.0,
    }
    resp = client.post("/backtests", json=body, headers=auth_headers)

    assert resp.status_code == HTTPStatus.OK
    assert resp.json()["trade_count"] >= 1


class _FakeAdvisor:
    """Stands in for PairsTradingAdvisor — no LLMClient/litellm call, just a
    scripted proposal, so this test never hits a real LLM API.
    """

    def __init__(self, llm: object) -> None:
        del llm

    async def propose(
        self, candidates: object, prior: PairsTradingProposal
    ) -> PairsTradingProposal:
        del candidates, prior
        return PairsTradingProposal(
            entry_z=2.0,
            formation_months=1,
            trading_months=1,
            buffer=0.1,
            selected=(SelectedPairWeight("NSE-RELIANCE", "NSE-TCS", 0.9),),
        )


def test_run_backtest_pairs_trading_with_advisor_routes_through_advisor(
    client: TestClient,
    duckdb_store: DuckDBStore,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("server.routers.backtest.PairsTradingAdvisor", _FakeAdvisor)

    def a_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 101.0

    def b_close(day: int) -> float:
        return 100.0 if day % 2 == 0 else 100.9

    formation_days = range(32)
    bars = [_pair_bar("NSE-RELIANCE", d, a_close(d)) for d in formation_days]
    bars += [_pair_bar("NSE-TCS", d, b_close(d)) for d in formation_days]
    bars += [_pair_bar("NSE-RELIANCE", d, 100.0) for d in (32, 33)]
    bars += [_pair_bar("NSE-TCS", d, 1.0) for d in (32, 33)]
    duckdb_store.write_bars(bars)

    body = {
        "strategy_name": "pairs_trading",
        "symbols": ["NSE-RELIANCE", "NSE-TCS"],
        "interval": "1d",
        "from": "2026-01-01T00:00:00Z",
        "to": "2026-03-01T00:00:00Z",
        "starting_cash": 100_000.0,
        "formation_months": 1,
        "trading_months": 1,
        "top_n_pairs": 1,
        "entry_z": 2.0,
        "use_advisor": True,
    }
    resp = client.post("/backtests", json=body, headers=auth_headers)

    assert resp.status_code == HTTPStatus.OK
    assert resp.json()["trade_count"] >= 1


def test_run_backtest_mean_reversion_routes_through_discriminated_union(
    client: TestClient, duckdb_store: DuckDBStore, auth_headers: dict[str, str]
) -> None:
    # Flat, then a sharp drop forces an oversold Bollinger/RSI entry.
    closes = [100.0] * 10 + [80.0, 82.0]
    duckdb_store.write_bars(
        [_bar(day, close) for day, close in enumerate(closes, start=1)]
    )

    body = {
        "strategy_name": "mean_reversion",
        "symbols": ["NSE-RELIANCE"],
        "interval": "1d",
        "from": "2026-01-01T00:00:00Z",
        "to": "2026-01-31T00:00:00Z",
        "starting_cash": 100_000.0,
        "bb_window": 10,
        "bb_std": 2.0,
        "rsi_period": 10,
        "rsi_buy_threshold": 30.0,
        "rsi_sell_threshold": 70.0,
        "quantity": 10,
    }
    resp = client.post("/backtests", json=body, headers=auth_headers)

    assert resp.status_code == HTTPStatus.OK
    assert resp.json()["trade_count"] >= 1
