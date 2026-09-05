from datetime import UTC, datetime

import pytest
from ingest.core.models import Bar
from quant.core.constants import FORECAST_SCALE_MAX
from quant.core.exceptions import InsufficientDataError
from quant.signals.time_series_momentum.signal import TimeSeriesMomentumSignal


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


def test_compute_returns_positive_sign_on_positive_trailing_return() -> None:
    signal = TimeSeriesMomentumSignal(window=3)
    raw = signal.compute(_bars([100.0, 100.0, 100.0, 110.0]))
    assert raw.value == 1.0
    assert raw.symbol == "RELIANCE"
    assert raw.name == "time_series_momentum"


def test_compute_returns_negative_sign_on_negative_trailing_return() -> None:
    signal = TimeSeriesMomentumSignal(window=3)
    raw = signal.compute(_bars([100.0, 100.0, 100.0, 90.0]))
    assert raw.value == -1.0


def test_compute_returns_zero_on_flat_trailing_return() -> None:
    signal = TimeSeriesMomentumSignal(window=3)
    raw = signal.compute(_bars([100.0, 100.0, 100.0, 100.0]))
    assert raw.value == 0.0


def test_compute_raises_insufficient_data_before_window_plus_one_bars() -> None:
    signal = TimeSeriesMomentumSignal(window=5)
    with pytest.raises(InsufficientDataError):
        signal.compute(_bars([1.0, 2.0]))


def test_scale_maps_sign_to_forecast_extremes() -> None:
    signal = TimeSeriesMomentumSignal(window=3)
    raw = signal.compute(_bars([100.0, 100.0, 100.0, 110.0]))
    forecast = signal.scale(raw)
    assert forecast.scaled_value == FORECAST_SCALE_MAX

    raw_down = signal.compute(_bars([100.0, 100.0, 100.0, 90.0]))
    assert signal.scale(raw_down).scaled_value == -FORECAST_SCALE_MAX


def test_init_raises_value_error_for_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window"):
        TimeSeriesMomentumSignal(window=0)
