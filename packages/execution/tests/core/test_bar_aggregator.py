from datetime import UTC, datetime

from execution.core.bar_aggregator import TickBarAggregator
from ingest.core.models import Tick


def _tick(ts: datetime, price: float, volume: int = 10) -> Tick:
    return Tick(symbol="NSE-RELIANCE", ts=ts, price=price, volume=volume, provider="test")


def test_first_tick_never_returns_a_bar() -> None:
    aggregator = TickBarAggregator(interval="1m")

    result = aggregator.add_tick(_tick(datetime(2026, 1, 1, 9, 15, 5, tzinfo=UTC), 100.0))

    assert result is None


def test_tick_within_same_bucket_returns_none() -> None:
    aggregator = TickBarAggregator(interval="1m")
    aggregator.add_tick(_tick(datetime(2026, 1, 1, 9, 15, 5, tzinfo=UTC), 100.0))

    result = aggregator.add_tick(_tick(datetime(2026, 1, 1, 9, 15, 45, tzinfo=UTC), 101.0))

    assert result is None


def test_tick_crossing_interval_boundary_returns_completed_bar() -> None:
    aggregator = TickBarAggregator(interval="1m")
    aggregator.add_tick(_tick(datetime(2026, 1, 1, 9, 15, 5, tzinfo=UTC), 100.0))
    aggregator.add_tick(_tick(datetime(2026, 1, 1, 9, 15, 45, tzinfo=UTC), 105.0))

    bar = aggregator.add_tick(_tick(datetime(2026, 1, 1, 9, 16, 1, tzinfo=UTC), 110.0))

    assert bar is not None
    assert bar.ts == datetime(2026, 1, 1, 9, 15, 0, tzinfo=UTC)
    assert bar.open == 100.0
    assert bar.high == 105.0
    assert bar.low == 100.0
    assert bar.close == 105.0
    assert bar.volume == 20


def test_flush_returns_the_in_progress_bar() -> None:
    aggregator = TickBarAggregator(interval="1m")
    aggregator.add_tick(_tick(datetime(2026, 1, 1, 9, 15, 5, tzinfo=UTC), 100.0))

    bar = aggregator.flush()

    assert bar is not None
    assert bar.close == 100.0


def test_flush_with_no_ticks_returns_none() -> None:
    aggregator = TickBarAggregator(interval="1m")

    assert aggregator.flush() is None


def test_unsupported_interval_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="unsupported interval"):
        TickBarAggregator(interval="not_an_interval")
