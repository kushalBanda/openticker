import pytest
from quant.core.exceptions import InsufficientDataError
from quant.features.rolling_stats import average_volume


def test_average_volume_matches_mean() -> None:
    assert average_volume([1000, 2000, 3000], 3) == pytest.approx(2000.0)


def test_average_volume_uses_only_last_window_values() -> None:
    assert average_volume([10000, 1000, 3000], 2) == pytest.approx(2000.0)


def test_average_volume_raises_when_insufficient_values() -> None:
    with pytest.raises(InsufficientDataError):
        average_volume([1000], 3)
