from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from quant.core.exceptions import InsufficientDataError
from quant.features.technicals import (
    bollinger_bands,
    exponential_moving_average,
    macd,
    moving_average,
    relative_strength_index,
    smoothed_moving_average,
)


def _series(values: list[float]) -> pd.Series:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    index = pd.DatetimeIndex([start + timedelta(days=i) for i in range(len(values))])
    return pd.Series(values, index=index, dtype=float)


def test_moving_average_matches_known_reference() -> None:
    result = moving_average(_series([1.0, 2.0, 3.0, 4.0, 5.0]), window=5)
    assert result.iloc[-1] == pytest.approx(3.0)
    result = moving_average(_series([10.0, 20.0, 30.0]), window=2)
    assert result.iloc[-1] == pytest.approx(25.0)


def test_moving_average_raises_when_insufficient_observations() -> None:
    with pytest.raises(InsufficientDataError):
        moving_average(_series([1.0, 2.0]), window=5)


def test_bollinger_bands_centered_on_moving_average() -> None:
    series = _series([100.0, 102.0, 98.0, 101.0, 99.0])
    bands = bollinger_bands(series, window=5, k=2.0)
    avg = moving_average(series, window=5).iloc[-1]
    assert bands["upper"].iloc[-1] > avg > bands["lower"].iloc[-1]


def test_smoothed_moving_average_seed_is_flat_mean() -> None:
    series = _series([1.0, 2.0, 3.0, 4.0, 5.0])
    result = smoothed_moving_average(series, window=5)
    assert result.iloc[-1] == pytest.approx(3.0)


def test_relative_strength_index_matches_hand_computed_seed() -> None:
    # closes: 44, 44.5, 45, 44.75, 45.5, 46 (period+1 == len, seed-only case)
    # diffs:  +0.5, +0.5, -0.25, +0.75, +0.5
    # gains:  0.5, 0.5, 0, 0.75, 0.5 -> avg_gain = 2.25 / 5 = 0.45
    # losses: 0, 0, 0.25, 0, 0      -> avg_loss = 0.25 / 5 = 0.05
    # rs = 0.45 / 0.05 = 9.0 -> rsi = 100 - (100 / 10) = 90.0
    series = _series([44.0, 44.5, 45.0, 44.75, 45.5, 46.0])
    result = relative_strength_index(series, window=5)
    assert result.iloc[-1] == pytest.approx(90.0)


def test_relative_strength_index_returns_100_when_no_losses() -> None:
    series = _series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    result = relative_strength_index(series, window=5)
    assert result.iloc[-1] == 100.0


def test_relative_strength_index_raises_when_insufficient_observations() -> None:
    with pytest.raises(InsufficientDataError):
        relative_strength_index(_series([1.0, 2.0, 3.0]), window=5)


def test_exponential_moving_average_matches_seed_on_first_value() -> None:
    series = _series([10.0, 20.0, 30.0])
    result = exponential_moving_average(series, beta=0.75)
    assert result.iloc[0] == pytest.approx(10.0)


def test_macd_zero_for_flat_prices() -> None:
    series = _series([100.0] * 30)
    result = macd(series)
    assert result.iloc[-1] == pytest.approx(0.0)
