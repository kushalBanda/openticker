from datetime import UTC, datetime
from http import HTTPStatus

from fastapi.testclient import TestClient
from strategy.core.ledger import LedgerEntry
from strategy.storage.ledger_store import LedgerStore


def _entry(day: int, cash_after: float) -> LedgerEntry:
    return LedgerEntry(
        symbol="NSE-RELIANCE",
        side="buy",
        quantity=10,
        fill_price=100.0,
        fill_ts=datetime(2026, 1, day, tzinfo=UTC),
        commission=1.0,
        cost_basis_before=0.0,
        realized_pnl=0.0,
        cash_after=cash_after,
        position_after=10 * day,
    )


def test_list_runs_empty(client: TestClient) -> None:
    resp = client.get("/backtests")
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {"run_ids": []}


def test_list_runs_returns_written_runs(
    client: TestClient, ledger_store: LedgerStore
) -> None:
    ledger_store.write_entries("run-1", [_entry(1, 9_000.0)])
    resp = client.get("/backtests")
    assert resp.json() == {"run_ids": ["run-1"]}


def test_get_trades_404_for_unknown_run(client: TestClient) -> None:
    resp = client.get("/backtests/no-such-run/trades")
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_get_trades_returns_entries(
    client: TestClient, ledger_store: LedgerStore
) -> None:
    ledger_store.write_entries("run-1", [_entry(1, 9_000.0)])
    resp = client.get("/backtests/run-1/trades")
    assert resp.status_code == HTTPStatus.OK
    body = resp.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "NSE-RELIANCE"


def test_get_metrics_returns_report(
    client: TestClient, ledger_store: LedgerStore
) -> None:
    ledger_store.write_entries(
        "run-1", [_entry(1, 9_000.0), _entry(2, 9_500.0)]
    )
    resp = client.get("/backtests/run-1/metrics")
    assert resp.status_code == HTTPStatus.OK
    body = resp.json()
    assert set(body) == {
        "total_return",
        "annualized_return",
        "max_drawdown",
        "sharpe_ratio",
        "exponential_std",
        "win_rate",
    }


def test_get_metrics_404_for_unknown_run(client: TestClient) -> None:
    resp = client.get("/backtests/no-such-run/metrics")
    assert resp.status_code == HTTPStatus.NOT_FOUND
