from datetime import UTC, datetime

import pytest
from strategy.metrics.performance import compute_metrics


def test_compute_metrics_known_equity_curve() -> None:
    # Two points, 365 days apart, 10% total return, no interim drawdown.
    equity_curve = [
        (datetime(2026, 1, 1, tzinfo=UTC), 100_000.0),
        (datetime(2027, 1, 1, tzinfo=UTC), 110_000.0),
    ]

    report = compute_metrics(equity_curve)

    assert report.cagr == pytest.approx(0.10, abs=1e-6)
    assert report.max_drawdown == 0.0
    assert report.win_rate == 1.0
    assert report.sharpe == 0.0  # single return, zero std dev, guarded


def test_compute_metrics_captures_drawdown_and_losing_periods() -> None:
    equity_curve = [
        (datetime(2026, 1, 1, tzinfo=UTC), 100_000.0),
        (datetime(2026, 1, 2, tzinfo=UTC), 120_000.0),
        (datetime(2026, 1, 3, tzinfo=UTC), 90_000.0),
        (datetime(2026, 1, 4, tzinfo=UTC), 108_000.0),
    ]

    report = compute_metrics(equity_curve)

    assert report.max_drawdown == pytest.approx(0.25, abs=1e-6)  # 120k -> 90k
    assert report.win_rate == pytest.approx(2 / 3, abs=1e-6)  # 2 of 3 periods positive


def test_compute_metrics_too_few_points_returns_zeros() -> None:
    report = compute_metrics([(datetime(2026, 1, 1, tzinfo=UTC), 100_000.0)])

    assert report.sharpe == 0.0
    assert report.max_drawdown == 0.0
    assert report.win_rate == 0.0
    assert report.cagr == 0.0
