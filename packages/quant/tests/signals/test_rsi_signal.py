from datetime import UTC, datetime

import pytest
from ingest.core.models import Bar
from quant.core.exceptions import InsufficientDataError
from quant.features.rolling_stats import simple_rsi
from quant.signals.rsi.signal import RsiSignal


def _bars(closes: list[float]) -> list[Bar]:
    return [
        Bar(
            symbol="RELIANCE",
            interval="1d",
            ts=datetime(2026, 1, 1, tzinfo=UTC),
            open=c,
            high=c,
            low=c,
            close=c,
            volume=1000,
            provider="synthetic",
        )
        for c in closes
    ]


def test_compute_returns_raw_signal_matching_simple_rsi() -> None:
    closes = [44, 44.5, 45, 44.75, 45.5, 46]
    signal = RsiSignal(period=5)
    raw = signal.compute(_bars(closes))
    assert raw.value == pytest.approx(simple_rsi(closes, period=5))
    assert raw.symbol == "RELIANCE"
    assert raw.interval == "1d"
    assert raw.name == "rsi"


def test_compute_raises_insufficient_data_before_period_plus_one_bars() -> None:
    signal = RsiSignal(period=14)
    with pytest.raises(InsufficientDataError):
        signal.compute(_bars([100.0, 101.0, 102.0]))


def test_scale_maps_fifty_to_zero() -> None:
    # closes alternate +1/-1: gains sum == losses sum -> RSI exactly 50
    signal = RsiSignal(period=4)
    raw = signal.compute(_bars([1.0, 2.0, 1.0, 2.0, 1.0]))
    assert raw.value == pytest.approx(50.0)
    forecast = signal.scale(raw)
    assert forecast.scaled_value == pytest.approx(0.0)


def test_scale_maps_100_to_positive_twenty() -> None:
    signal = RsiSignal(period=5)
    raw = signal.compute(_bars([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))
    assert raw.value == 100.0
    forecast = signal.scale(raw)
    assert forecast.scaled_value == pytest.approx(20.0)


def test_init_raises_value_error_for_non_positive_period() -> None:
    with pytest.raises(ValueError, match="period"):
        RsiSignal(period=0)
