import pytest
from quant.core.exceptions import InsufficientDataError
from quant.features.rolling_stats import simple_rsi


def test_simple_rsi_matches_known_reference() -> None:
    # 5-period example worked out by hand:
    # closes: 44, 44.5, 45, 44.75, 45.5, 46
    # diffs:  +0.5, +0.5, -0.25, +0.75, +0.5
    # gains:  0.5, 0.5, 0, 0.75, 0.5 -> avg_gain = 2.25 / 5 = 0.45
    # losses: 0, 0, 0.25, 0, 0      -> avg_loss = 0.25 / 5 = 0.05
    # rs = 0.45 / 0.05 = 9.0
    # rsi = 100 - (100 / (1 + 9.0)) = 100 - 10 = 90.0
    closes = [44, 44.5, 45, 44.75, 45.5, 46]
    assert simple_rsi(closes, period=5) == pytest.approx(90.0)


def test_simple_rsi_raises_when_insufficient_closes() -> None:
    with pytest.raises(InsufficientDataError):
        simple_rsi([1.0, 2.0, 3.0], period=5)


def test_simple_rsi_returns_100_when_no_losses() -> None:
    closes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert simple_rsi(closes, period=5) == 100.0
