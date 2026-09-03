from datetime import UTC, datetime, timedelta

import pytest
from ingest.core.models import Bar
from quant.evaluation.forward_returns import forward_returns


def _bars(closes: list[float]) -> list[Bar]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(
            symbol="RELIANCE",
            interval="1d",
            ts=base + timedelta(days=i),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1000,
            provider="kite",
        )
        for i, close in enumerate(closes)
    ]


def test_forward_returns_computes_correct_pct_change() -> None:
    bars = _bars([100.0, 110.0, 121.0, 108.9, 130.0])

    result = forward_returns(bars, horizon=2)

    assert result[0] == pytest.approx(0.21)  # 121/100 - 1
    assert result[1] == pytest.approx(-0.01)  # 108.9/110 - 1
    assert result[2] == pytest.approx(0.07438016528925569)  # 130/121 - 1


def test_forward_returns_last_n_bars_are_none() -> None:
    bars = _bars([100.0, 110.0, 121.0, 108.9, 130.0])

    result = forward_returns(bars, horizon=3)

    assert result[-3:] == [None, None, None]
    assert result[0] is not None
    assert result[1] is not None


def test_forward_returns_raises_on_non_positive_horizon() -> None:
    bars = _bars([100.0, 110.0])

    with pytest.raises(ValueError, match="horizon must be greater than 0"):
        forward_returns(bars, horizon=0)
