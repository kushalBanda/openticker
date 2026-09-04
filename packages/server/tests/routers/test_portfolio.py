from datetime import UTC, datetime
from http import HTTPStatus

from fastapi.testclient import TestClient
from strategy.core.ledger import LedgerEntry
from strategy.storage.ledger_store import LedgerStore


def _entry(symbol: str, position_after: int, cash_after: float) -> LedgerEntry:
    return LedgerEntry(
        symbol=symbol,
        side="buy",
        quantity=10,
        fill_price=100.0,
        fill_ts=datetime(2026, 1, 1, tzinfo=UTC),
        commission=1.0,
        cost_basis_before=0.0,
        realized_pnl=0.0,
        cash_after=cash_after,
        position_after=position_after,
    )


def test_get_positions_404_for_unknown_run(client: TestClient) -> None:
    resp = client.get("/portfolio/no-such-run/positions")
    assert resp.status_code == HTTPStatus.NOT_FOUND


def test_get_positions_returns_latest_per_symbol(
    client: TestClient, ledger_store: LedgerStore
) -> None:
    ledger_store.write_entries(
        "run-1",
        [
            _entry("NSE-RELIANCE", 10, 9_000.0),
            _entry("NSE-TCS", 5, 8_500.0),
        ],
    )
    resp = client.get("/portfolio/run-1/positions")
    assert resp.status_code == HTTPStatus.OK
    body = resp.json()
    assert body["run_id"] == "run-1"
    symbols = {p["symbol"]: p["quantity"] for p in body["positions"]}
    assert symbols == {"NSE-RELIANCE": 10, "NSE-TCS": 5}
