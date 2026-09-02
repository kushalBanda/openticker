from datetime import UTC, datetime

import pytest
from ingest.core.models import Bar
from quant.core.exceptions import InsufficientDataError
from quant.signals.sma.signal import SmaSignal


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


def test_compute_returns_raw_signal_matching_simple_moving_average() -> None:
    signal = SmaSignal(window=3)
    raw = signal.compute(_bars([10.0, 20.0, 30.0]))
    assert raw.value == 20.0
    assert raw.symbol == "RELIANCE"
    assert raw.name == "sma"


def test_compute_raises_insufficient_data_before_window_bars() -> None:
    signal = SmaSignal(window=5)
    with pytest.raises(InsufficientDataError):
        signal.compute(_bars([1.0, 2.0]))


def test_scale_is_a_documented_pass_through() -> None:
    signal = SmaSignal(window=3)
    raw = signal.compute(_bars([10.0, 20.0, 30.0]))
    forecast = signal.scale(raw)
    assert forecast.scaled_value == raw.value


def test_init_raises_value_error_for_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window"):
        SmaSignal(window=0)
