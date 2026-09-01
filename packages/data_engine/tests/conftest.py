from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from data_engine.core.models import Bar, Tick
from data_engine.storage.duckdb_store import DuckDBStore


class FakeAdapter:
    def __init__(self, bars: list[Bar] | None = None) -> None:
        self.bars = bars or []
        self.fetch_historical_calls = 0
        self.fetch_historical_ranges: list[tuple[datetime, datetime]] = []

    async def connect(self) -> None:
        pass

    async def fetch_historical(
        self, symbol: str, interval: str, from_: datetime, to: datetime
    ) -> list[Bar]:
        self.fetch_historical_calls += 1
        self.fetch_historical_ranges.append((from_, to))
        return [b for b in self.bars if from_ <= b.ts <= to]

    async def subscribe_live(self, symbols: list[str]) -> AsyncIterator[Tick]:
        for symbol in symbols:
            yield Tick(
                symbol=symbol,
                ts=datetime.now(UTC),
                price=100.0,
                volume=1,
                provider="fake",
            )

    async def disconnect(self) -> None:
        pass


@pytest.fixture
def duckdb_store(tmp_path: Path) -> DuckDBStore:
    return DuckDBStore(db_path=tmp_path / "test.duckdb")
