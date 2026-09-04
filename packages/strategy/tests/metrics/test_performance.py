from datetime import UTC, datetime, timedelta

import pytest
from strategy.metrics.performance import compute_metrics


def _curve(values: list[float]) -> list[tuple[datetime, float]]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def test_compute_metrics_known_equity_curve() -> None:
    # Three flat-then-rising points, 10% total return end to end, no
    # interim drawdown.
    equity_curve = _curve([100_000.0, 105_000.0, 110_000.0])

    report = compute_metrics(equity_curve)

    assert report.total_return == pytest.approx(0.10, abs=1e-6)
    assert report.max_drawdown == 0.0
    assert report.win_rate == 1.0
    assert report.sharpe_ratio > 0.0
    assert report.exponential_std > 0.0


def test_compute_metrics_captures_drawdown_and_losing_periods() -> None:
    equity_curve = _curve([100_000.0, 120_000.0, 90_000.0, 108_000.0])

    report = compute_metrics(equity_curve)

    # 120k -> 90k, negative convention: a drawdown is a loss.
    assert report.max_drawdown == pytest.approx(-0.25, abs=1e-6)
    assert report.win_rate == pytest.approx(2 / 3, abs=1e-6)


def test_compute_metrics_too_few_points_returns_zeros() -> None:
    report = compute_metrics(_curve([100_000.0]))

    assert report.total_return == 0.0
    assert report.annualized_return == 0.0
    assert report.sharpe_ratio == 0.0
    assert report.max_drawdown == 0.0
    assert report.exponential_std == 0.0
    assert report.win_rate == 0.0


def test_compute_metrics_flat_equity_curve_is_all_zero() -> None:
    equity_curve = _curve([100_000.0, 100_000.0, 100_000.0])

    report = compute_metrics(equity_curve)

    assert report.total_return == pytest.approx(0.0, abs=1e-9)
    assert report.annualized_return == pytest.approx(0.0, abs=1e-9)
    assert report.max_drawdown == 0.0
    assert report.sharpe_ratio == 0.0
    assert report.exponential_std == 0.0
    assert report.win_rate == 0.0


def test_compute_metrics_short_run_annualized_return_amplifies_total_return() -> None:
    # 10 calendar days, 2% total return end to end. No short-run guard:
    # annualized_return compounds this into a much bigger number, matching
    # the underlying formula's real behavior. total_return stays the
    # honest, small number alongside it.
    values = [100_000.0] * 9 + [102_000.0]
    report = compute_metrics(_curve(values))

    assert report.total_return == pytest.approx(0.02, abs=1e-6)
    assert report.annualized_return > report.total_return
