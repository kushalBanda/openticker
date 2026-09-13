"""Tests for plugin/lib/math/indicators/_common.py."""

import pandas as pd
import pytest

from lib.math.exceptions import InsufficientDataError
from lib.math.indicators._common import _trailing_reading


def test_trailing_reading_returns_latest_and_last_n() -> None:
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    reading = _trailing_reading(series, trailing_count=3)
    assert reading.latest == 7.0
    assert reading.trailing == [5.0, 6.0, 7.0]


def test_trailing_reading_drops_leading_nan() -> None:
    series = pd.Series([float("nan"), float("nan"), 3.0, 4.0])
    reading = _trailing_reading(series, trailing_count=5)
    assert reading.latest == 4.0
    assert reading.trailing == [3.0, 4.0]


def test_trailing_reading_raises_when_series_is_all_nan() -> None:
    series = pd.Series([float("nan"), float("nan")])
    with pytest.raises(InsufficientDataError):
        _trailing_reading(series)
