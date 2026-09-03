from datetime import UTC, datetime

import pytest
from ingest.core.models import Bar
from quant.core.exceptions import InsufficientDataError
from quant.signals.above_average_volume.signal import AboveAverageVolumeSignal


def _bars(volumes: list[int]) -> list[Bar]:
    return [
        Bar(
            symbol="RELIANCE",
            interval="1d",
            ts=datetime(2026, 1, 1, tzinfo=UTC),
            open=10.0,
            high=10.0,
            low=10.0,
            close=10.0,
            volume=v,
            provider="synthetic",
        )
        for v in volumes
    ]


def test_compute_gives_positive_value_for_above_average_volume() -> None:
    signal = AboveAverageVolumeSignal(window=3)
    raw = signal.compute(_bars([1000, 1000, 1000, 2000]))
    assert raw.value == pytest.approx(1.0)
    assert raw.name == "above_average_volume"


def test_compute_gives_negative_value_for_below_average_volume() -> None:
    signal = AboveAverageVolumeSignal(window=3)
    raw = signal.compute(_bars([1000, 1000, 1000, 500]))
    assert raw.value == pytest.approx(-0.5)


def test_compute_raises_insufficient_data_before_window_plus_one_bars() -> None:
    signal = AboveAverageVolumeSignal(window=5)
    with pytest.raises(InsufficientDataError):
        signal.compute(_bars([1000, 1000]))


def test_scale_is_a_documented_pass_through() -> None:
    signal = AboveAverageVolumeSignal(window=3)
    raw = signal.compute(_bars([1000, 1000, 1000, 2000]))
    forecast = signal.scale(raw)
    assert forecast.scaled_value == raw.value


def test_init_raises_value_error_for_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window"):
        AboveAverageVolumeSignal(window=0)
