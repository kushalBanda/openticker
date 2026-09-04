from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ingest.core.engine import DataEngine
from ingest.core.models import Bar, Tick
from ingest.storage.duckdb_store import DuckDBStore
from server.app import create_app
from server.core.deps import get_adapters, get_data_engine, get_ledger_store
from strategy.storage.ledger_store import LedgerStore


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
def duckdb_store(tmp_path: Path) -> DuckDBStore:
    return DuckDBStore(db_path=tmp_path / "market.duckdb")


@pytest.fixture
def fake_adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def data_engine(
    duckdb_store: DuckDBStore, fake_adapter: FakeAdapter
) -> DataEngine:
    return DataEngine(
        adapters={"kite": fake_adapter},
        store=duckdb_store,
        provider_routes={"NSE-RELIANCE": "kite", "RELIANCE": "kite"},
    )


@pytest.fixture
def client(
    ledger_store: LedgerStore, data_engine: DataEngine, fake_adapter: FakeAdapter
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_ledger_store] = lambda: ledger_store
    app.dependency_overrides[get_data_engine] = lambda: data_engine
    app.dependency_overrides[get_adapters] = lambda: {"kite": fake_adapter}
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
