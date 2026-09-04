from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from fastapi.testclient import TestClient
from strategy.core.ledger import LedgerEntry
from strategy.storage.equity_curve_store import EquityCurveStore
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


def _daily_equity_curve(values: list[float]) -> list[tuple[datetime, float]]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_list_runs_empty(client: TestClient) -> None:
    resp = client.get("/backtests")
    assert resp.status_code == HTTPStatus.OK
    body = resp.json()
    assert body["run_ids"] == []
    assert body["total"] == 0
    assert body["page"] == 1
    assert body["pages"] == 0


def test_list_runs_returns_written_runs(
    client: TestClient, ledger_store: LedgerStore
) -> None:
    ledger_store.write_entries("run-1", [_entry(1, 9_000.0)])
    resp = client.get("/backtests")
    body = resp.json()
    assert body["run_ids"] == ["run-1"]
    assert body["total"] == 1
    assert body["pages"] == 1


def test_list_runs_paginates(
    client: TestClient, ledger_store: LedgerStore
) -> None:
    for i in range(3):
        ledger_store.write_entries(f"run-{i}", [_entry(1, 9_000.0)])

    resp = client.get("/backtests", params={"page": 1, "page_size": 2})
    body = resp.json()
    assert body["run_ids"] == ["run-0", "run-1"]
    assert body["total"] == 3
    assert body["pages"] == 2

    resp2 = client.get("/backtests", params={"page": 2, "page_size": 2})
    body2 = resp2.json()
    assert body2["run_ids"] == ["run-2"]


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
    assert body["total"] == 1
    assert len(body["trades"]) == 1
    assert body["trades"][0]["symbol"] == "NSE-RELIANCE"


def test_get_trades_paginates(
    client: TestClient, ledger_store: LedgerStore
) -> None:
    entries = [_entry(day, 9_000.0 + day) for day in range(1, 4)]
    ledger_store.write_entries("run-1", entries)

    resp = client.get("/backtests/run-1/trades", params={"page_size": 2})
    body = resp.json()
    assert len(body["trades"]) == 2
    assert body["total"] == 3
    assert body["pages"] == 2


def test_get_metrics_returns_report(
    client: TestClient, equity_curve_store: EquityCurveStore
) -> None:
    equity_curve_store.write_points(
        "run-1", _daily_equity_curve([100_000.0, 100_500.0, 101_000.0])
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


def test_get_metrics_uses_daily_equity_curve_not_irregular_fill_gaps(
    client: TestClient, equity_curve_store: EquityCurveStore
) -> None:
    # Same shape of run that used to 422 when metrics were built from
    # sparse trade-fill timestamps (deltas 14/2/22 days averaging into
    # a bucket gap): a daily mark-to-market curve stays under the 2.1-day
    # daily-bucket threshold regardless of how sparsely the strategy
    # actually traded, so this now succeeds.
    values = [100_000.0] * 87
    equity_curve_store.write_points("run-1", _daily_equity_curve(values))

    resp = client.get("/backtests/run-1/metrics")

    assert resp.status_code == HTTPStatus.OK
