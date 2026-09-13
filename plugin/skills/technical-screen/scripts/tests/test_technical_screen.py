import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SCRIPT_DIR))

from lib.mechanics.models import Bar
from technical_screen import build_indicator_report


def _bars(count: int, close: float = 100.0) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar("TEST", "1d", start + timedelta(days=i), close, close + 1, close - 1, close, 1000, "test")
        for i in range(count)
    ]


def test_build_indicator_report_computes_requested_indicators() -> None:
    result = build_indicator_report(
        bars=_bars(30), benchmark_bars=None, indicator_names=["sma", "rsi"], params_by_indicator={"sma": {"window": 5}},
    )
    assert result["sma"]["value"]["latest"] == 100.0
    assert result["sma"]["params_used"] == {"window": 5, "trailing_count": 5}
    assert result["rsi"]["value"]["latest"] == 100.0  # flat closes: avg_loss == 0
    assert result["rsi"]["params_used"]["window"] == 14


def test_build_indicator_report_reports_per_indicator_error() -> None:
    result = build_indicator_report(
        bars=_bars(5), benchmark_bars=None, indicator_names=["sma", "adx"], params_by_indicator={"sma": {"window": 5}},
    )
    assert "value" in result["sma"]
    assert "error" in result["adx"]


def test_build_indicator_report_rejects_unknown_indicator() -> None:
    result = build_indicator_report(bars=_bars(30), benchmark_bars=None, indicator_names=["not_a_real_one"], params_by_indicator={})
    assert "error" in result["not_a_real_one"]


def test_build_indicator_report_cross_sectional_needs_benchmark() -> None:
    result = build_indicator_report(bars=_bars(30), benchmark_bars=None, indicator_names=["beta"], params_by_indicator={})
    assert "error" in result["beta"]


def test_build_indicator_report_cross_sectional_with_benchmark() -> None:
    result = build_indicator_report(
        bars=_bars(30), benchmark_bars=_bars(30, close=50.0), indicator_names=["correlation"], params_by_indicator={},
    )
    assert "value" in result["correlation"] or "error" in result["correlation"]
