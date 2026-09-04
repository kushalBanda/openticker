from datetime import UTC, datetime, timedelta

import pytest
from quant.core.exceptions import InsufficientDataError
from quant.features.statistics import (
    annualized_return,
    exponential_std,
    max_drawdown,
    sharpe_ratio,
    total_return,
)


def _days(n: int) -> list[datetime]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [start + timedelta(days=i) for i in range(n)]


def test_total_return_matches_known_reference() -> None:
    assert total_return([100.0, 110.0]) == pytest.approx(0.10)


def test_total_return_flat_price_is_zero() -> None:
    assert total_return([100.0, 100.0, 100.0]) == 0.0


def test_total_return_raises_when_insufficient_closes() -> None:
    with pytest.raises(InsufficientDataError):
        total_return([100.0])


def test_annualized_return_matches_hand_computed_value() -> None:
    # 10% total return over exactly 365 calendar days, no risk-free drag.
    closes = [100.0, 110.0]
    timestamps = [datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)]
    result = annualized_return(closes, timestamps)
    assert result == pytest.approx(0.10, abs=1e-3)


def test_annualized_return_short_span_is_larger_than_total_return() -> None:
    # A small return compounded over a much-shorter-than-a-year span
    # annualizes to a bigger number than the raw total return. This is
    # expected, matching behavior, not a bug to special-case away.
    closes = [100.0, 102.0]
    timestamps = _days(2)
    assert annualized_return(closes, timestamps) > total_return(closes)


def test_annualized_return_flat_price_is_zero() -> None:
    closes = [100.0] * 10
    timestamps = _days(10)
    assert annualized_return(closes, timestamps) == pytest.approx(0.0)


def test_annualized_return_removes_risk_free_drag() -> None:
    closes = [100.0, 110.0]
    timestamps = [datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)]
    no_rate = annualized_return(closes, timestamps, risk_free_rate=0.0)
    with_rate = annualized_return(closes, timestamps, risk_free_rate=0.05)
    assert with_rate < no_rate


def test_annualized_return_raises_when_insufficient_closes() -> None:
    with pytest.raises(InsufficientDataError):
        annualized_return([100.0], _days(1))


def test_annualized_return_raises_on_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="annualized_return"):
        annualized_return([100.0, 110.0], _days(3))


def test_max_drawdown_flat_price_is_zero() -> None:
    assert max_drawdown([100.0, 100.0, 100.0]) == 0.0


def test_max_drawdown_matches_known_reference() -> None:
    # Peak at 120, trough at 90: (90 - 120) / 120 = -0.25
    closes = [100.0, 120.0, 110.0, 90.0, 95.0]
    assert max_drawdown(closes) == pytest.approx(-0.25)


def test_max_drawdown_recovers_after_new_peak() -> None:
    closes = [100.0, 80.0, 100.0, 130.0, 100.0]
    # Worst drawdown: (80-100)/100 = -0.2, then (100-130)/130 ≈ -0.2308
    assert max_drawdown(closes) == pytest.approx((100.0 - 130.0) / 130.0)


def test_max_drawdown_raises_when_insufficient_closes() -> None:
    with pytest.raises(InsufficientDataError):
        max_drawdown([100.0])


def test_sharpe_ratio_zero_for_flat_prices() -> None:
    assert sharpe_ratio([100.0, 100.0, 100.0], _days(3)) == 0.0


def test_sharpe_ratio_positive_for_steady_gains() -> None:
    closes = [100.0, 101.0, 102.01, 103.03, 104.06]
    assert sharpe_ratio(closes, _days(5)) > 0.0


def test_sharpe_ratio_raises_when_insufficient_closes() -> None:
    with pytest.raises(InsufficientDataError):
        sharpe_ratio([100.0, 101.0], _days(2))


def test_sharpe_ratio_raises_on_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="sharpe_ratio"):
        sharpe_ratio([100.0, 101.0, 102.0], _days(2))


def test_exponential_std_zero_for_flat_prices() -> None:
    assert exponential_std([100.0, 100.0, 100.0, 100.0], beta=0.75) == 0.0


def test_exponential_std_positive_for_varying_returns() -> None:
    closes = [100.0, 102.0, 99.96, 101.9592, 99.920016]
    assert exponential_std(closes, beta=0.75) > 0.0


def test_exponential_std_raises_on_invalid_beta() -> None:
    with pytest.raises(ValueError, match="beta"):
        exponential_std([100.0, 101.0, 102.0], beta=1.0)
    with pytest.raises(ValueError, match="beta"):
        exponential_std([100.0, 101.0, 102.0], beta=-0.1)


def test_exponential_std_raises_when_insufficient_closes() -> None:
    with pytest.raises(InsufficientDataError):
        exponential_std([100.0], beta=0.75)
