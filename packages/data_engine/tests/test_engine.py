from datetime import UTC, datetime

from conftest import FakeAdapter
from data_engine.core.engine import DataEngine
from data_engine.core.models import Bar
from data_engine.storage.duckdb_store import DuckDBStore


async def test_tracer_bullet_fetch_historical_end_to_end(duckdb_store: DuckDBStore) -> None:
    fake_bars = [
        Bar(
            symbol="RELIANCE",
            interval="1d",
            ts=datetime(2026, 1, 2, tzinfo=UTC),
            open=100.0,
            high=105.0,
            low=99.0,
            close=104.0,
            volume=1000,
            provider="fake",
        ),
        Bar(
            symbol="RELIANCE",
            interval="1d",
            ts=datetime(2026, 1, 3, tzinfo=UTC),
            open=104.0,
            high=108.0,
            low=103.0,
            close=107.0,
            volume=1200,
            provider="fake",
        ),
    ]
    adapter = FakeAdapter(bars=fake_bars)
    engine = DataEngine(
        adapters={"fake": adapter},
        store=duckdb_store,
        provider_routes={"RELIANCE": "fake"},
    )

    result = await engine.fetch_historical(
        "RELIANCE", "1d", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 4, tzinfo=UTC)
    )

    assert len(result) == 2
    assert result[0].close == 104.0
    assert result[1].close == 107.0
    assert adapter.fetch_historical_calls == 1
