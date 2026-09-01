from datetime import UTC, datetime

import pytest
from conftest import FakeAdapter
from data_engine.core.engine import DataEngine
from data_engine.core.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    RateLimitError,
)
from data_engine.core.models import Bar
from data_engine.storage.duckdb_store import DuckDBStore


async def test_tracer_bullet_fetch_historical_end_to_end(
    duckdb_store: DuckDBStore,
) -> None:
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
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 4, tzinfo=UTC),
    )

    assert len(result) == 2
    assert result[0].close == 104.0
    assert result[1].close == 107.0
    assert adapter.fetch_historical_calls == 1


async def test_fetch_historical_extends_cached_range_fetches_only_the_gap(
    duckdb_store: DuckDBStore,
) -> None:
    all_bars = [
        Bar(
            symbol="RELIANCE",
            interval="1d",
            ts=datetime(2026, 1, day, tzinfo=UTC),
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            volume=100,
            provider="fake",
        )
        for day in range(1, 6)
    ]
    adapter = FakeAdapter(bars=all_bars)
    engine = DataEngine(
        adapters={"fake": adapter},
        store=duckdb_store,
        provider_routes={"RELIANCE": "fake"},
    )

    first = await engine.fetch_historical(
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert len(first) == 2
    assert adapter.fetch_historical_calls == 1

    extended = await engine.fetch_historical(
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 5, tzinfo=UTC),
    )

    assert len(extended) == 5
    assert adapter.fetch_historical_calls == 2
    second_call_from, second_call_to = adapter.fetch_historical_ranges[1]
    assert second_call_from > datetime(2026, 1, 2, tzinfo=UTC)
    assert second_call_to == datetime(2026, 1, 5, tzinfo=UTC)


async def test_explicit_provider_override_reaches_the_named_adapter(
    duckdb_store: DuckDBStore,
) -> None:
    # Uses two different symbols, not the same symbol against two providers.
    # The DuckDB cache key is (symbol, interval, ts), it does not include
    # provider, so two providers' bars for the same symbol/ts collide in
    # storage, an explicit override cannot cleanly cross-check the same
    # range from two sources under the current cache design. That's a real
    # limitation, not covered by this test, see docs/plans/data-engine/00-status.md.
    bar_reliance = Bar(
        symbol="RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, 2, tzinfo=UTC),
        open=100.0,
        high=100.0,
        low=100.0,
        close=100.0,
        volume=1,
        provider="kite",
    )
    bar_infy = Bar(
        symbol="INFY",
        interval="1d",
        ts=datetime(2026, 1, 2, tzinfo=UTC),
        open=200.0,
        high=200.0,
        low=200.0,
        close=200.0,
        volume=1,
        provider="groww",
    )
    kite_adapter = FakeAdapter(bars=[bar_reliance])
    groww_adapter = FakeAdapter(bars=[bar_infy])
    engine = DataEngine(
        adapters={"kite": kite_adapter, "groww": groww_adapter},
        store=duckdb_store,
        provider_routes={"RELIANCE": "kite", "INFY": "kite"},
    )

    default_result = await engine.fetch_historical(
        "RELIANCE",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert default_result[0].close == 100.0
    assert kite_adapter.fetch_historical_calls == 1
    assert groww_adapter.fetch_historical_calls == 0

    override_result = await engine.fetch_historical(
        "INFY",
        "1d",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 3, tzinfo=UTC),
        provider="groww",
    )
    assert override_result[0].close == 200.0
    assert groww_adapter.fetch_historical_calls == 1


async def test_fetch_historical_unmapped_symbol_raises(
    duckdb_store: DuckDBStore,
) -> None:
    engine = DataEngine(
        adapters={"kite": FakeAdapter()},
        store=duckdb_store,
        provider_routes={},
    )

    with pytest.raises(DataUnavailableError):
        await engine.fetch_historical(
            "UNMAPPED",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        )


async def test_fetch_historical_auth_expired_propagates(
    duckdb_store: DuckDBStore,
) -> None:
    adapter = FakeAdapter(raises=AuthExpiredError("session expired"))
    engine = DataEngine(
        adapters={"fake": adapter},
        store=duckdb_store,
        provider_routes={"RELIANCE": "fake"},
    )

    with pytest.raises(AuthExpiredError):
        await engine.fetch_historical(
            "RELIANCE",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        )
    assert adapter.fetch_historical_calls == 1


async def test_fetch_historical_rate_limit_propagates(
    duckdb_store: DuckDBStore,
) -> None:
    adapter = FakeAdapter(raises=RateLimitError("too many requests"))
    engine = DataEngine(
        adapters={"fake": adapter},
        store=duckdb_store,
        provider_routes={"RELIANCE": "fake"},
    )

    with pytest.raises(RateLimitError):
        await engine.fetch_historical(
            "RELIANCE",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        )
    assert adapter.fetch_historical_calls == 1


async def test_fetch_historical_data_unavailable_propagates(
    duckdb_store: DuckDBStore,
) -> None:
    adapter = FakeAdapter(raises=DataUnavailableError("symbol not found upstream"))
    engine = DataEngine(
        adapters={"fake": adapter},
        store=duckdb_store,
        provider_routes={"RELIANCE": "fake"},
    )

    with pytest.raises(DataUnavailableError):
        await engine.fetch_historical(
            "RELIANCE",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        )
    assert adapter.fetch_historical_calls == 1
