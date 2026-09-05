from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ingest.core.models import Bar, Tick
from ingest.storage.duckdb_store import DuckDBStore
from server.app import create_app
from server.core.deps import (
    get_adapter,
    get_duckdb_store,
    get_equity_curve_store,
    get_ledger_store,
)
from server.core.security import create_session_token
from strategy.storage.equity_curve_store import EquityCurveStore
from strategy.storage.ledger_store import LedgerStore

_TEST_JWT_SECRET = "test-secret-at-least-32-bytes-long"


class FakeAdapter:
    """Mirrors ingest/tests/conftest.py's FakeAdapter — same shape, kept
    separate since server's tests must not depend on ingest's test package."""

    def __init__(self, bars: list[Bar] | None = None) -> None:
        self.bars = bars or []
        self.fetch_historical_calls = 0

    async def connect(self) -> None:
        pass

    async def fetch_historical(
        self, symbol: str, interval: str, from_: datetime, to: datetime
    ) -> list[Bar]:
        self.fetch_historical_calls += 1
        return [b for b in self.bars if from_ <= b.ts <= to]

    async def subscribe_live(self, symbols: list[str]) -> AsyncIterator[Tick]:
        return
        yield  # pragma: no cover - makes this an async generator, never runs

    async def disconnect(self) -> None:
        pass


@pytest.fixture
def ledger_store(tmp_path: Path) -> LedgerStore:
    return LedgerStore(db_path=tmp_path / "ledger.duckdb")


@pytest.fixture
def equity_curve_store(tmp_path: Path) -> EquityCurveStore:
    return EquityCurveStore(db_path=tmp_path / "ledger.duckdb")


@pytest.fixture
def duckdb_store(tmp_path: Path) -> DuckDBStore:
    return DuckDBStore(db_path=tmp_path / "market.duckdb")


@pytest.fixture
def fake_adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def session_token() -> str:
    return create_session_token(
        "kite", {"api_key": "test-key", "access_token": "test-token"}, _TEST_JWT_SECRET
    )


@pytest.fixture
def auth_headers(session_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token}"}


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    ledger_store: LedgerStore,
    equity_curve_store: EquityCurveStore,
    duckdb_store: DuckDBStore,
    fake_adapter: FakeAdapter,
) -> Iterator[TestClient]:
    monkeypatch.setenv("JWT_SECRET_KEY", _TEST_JWT_SECRET)

    # The app's startup lifespan fetches NSE's live index CSVs; tests must
    # not depend on real network access, so stub it out here.
    async def _fake_fetch_index_constituents(index_name: str) -> list[str]:
        return []

    monkeypatch.setattr(
        "server.app.fetch_index_constituents", _fake_fetch_index_constituents
    )

    app = create_app()
    app.dependency_overrides[get_ledger_store] = lambda: ledger_store
    app.dependency_overrides[get_equity_curve_store] = lambda: equity_curve_store
    app.dependency_overrides[get_duckdb_store] = lambda: duckdb_store
    app.dependency_overrides[get_adapter] = lambda: fake_adapter
    with TestClient(app) as test_client:
        yield test_client


def bar(symbol: str, day: int, close: float = 100.0) -> Bar:
    return Bar(
        symbol=symbol,
        interval="1d",
        ts=datetime(2026, 1, day, tzinfo=UTC),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000,
        provider="kite",
    )
