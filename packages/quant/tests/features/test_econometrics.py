from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from quant.core.exceptions import InsufficientDataError
from quant.features.econometrics import (
    ReturnKind,
    annualize,
    beta,
    change,
    correlation,
    index_normalize,
    prices,
    returns,
    volatility,
)


def _series(values: list[float]) -> pd.Series:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    index = pd.DatetimeIndex([start + timedelta(days=i) for i in range(len(values))])
    return pd.Series(values, index=index, dtype=float)


def test_returns_simple_matches_known_reference() -> None:
    result = returns(_series([100.0, 110.0]))
    assert result.iloc[-1] == pytest.approx(0.10)


def test_returns_absolute_matches_known_reference() -> None:
    result = returns(_series([100.0, 110.0]), kind=ReturnKind.ABSOLUTE)
    assert result.iloc[-1] == pytest.approx(10.0)


def test_prices_inverts_returns() -> None:
    series = _series([100.0, 110.0, 99.0])
    ret = returns(series)
    reconstructed = prices(ret.dropna(), initial=100.0)
    assert reconstructed.iloc[-1] == pytest.approx(series.iloc[-1])


def test_index_normalize_starts_at_initial() -> None:
    result = index_normalize(_series([50.0, 100.0, 150.0]), initial=1.0)
    assert result.iloc[0] == pytest.approx(1.0)
    assert result.iloc[-1] == pytest.approx(3.0)


def test_change_is_difference_from_first_value() -> None:
    result = change(_series([100.0, 110.0, 90.0]))
    assert result.iloc[0] == 0.0
    assert result.iloc[-1] == pytest.approx(-10.0)


def test_annualize_scales_by_sqrt_of_factor() -> None:
    series = _series([1.0] * 5)  # daily spacing -> factor 252
    result = annualize(series)
    assert result.iloc[0] == pytest.approx(252**0.5)


def test_volatility_positive_for_varying_returns() -> None:
    series = _series([100.0, 101.0, 99.0, 102.0, 98.0])
    result = volatility(series)
    assert result.iloc[-1] > 0.0


def test_volatility_raises_when_insufficient_observations() -> None:
    with pytest.raises(InsufficientDataError):
        volatility(_series([100.0, 101.0]), window=5)


def test_correlation_is_one_for_identical_series() -> None:
    series = _series([100.0, 101.0, 99.0, 102.0, 98.0])
    assert correlation(series, series) == pytest.approx(1.0)


def test_correlation_raises_when_insufficient_observations() -> None:
    with pytest.raises(InsufficientDataError):
        correlation(_series([100.0]), _series([100.0]))


def test_beta_is_one_for_identical_series() -> None:
    series = _series([100.0, 101.0, 99.0, 102.0, 98.0])
    assert beta(series, series) == pytest.approx(1.0)


def test_beta_raises_when_benchmark_has_zero_variance() -> None:
    with pytest.raises(InsufficientDataError):
        beta(_series([100.0, 101.0, 99.0]), _series([100.0, 100.0, 100.0]))
