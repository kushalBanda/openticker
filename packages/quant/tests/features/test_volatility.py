import pytest
from quant.core.exceptions import InsufficientDataError
from quant.features.volatility import realized_volatility


def test_realized_volatility_matches_known_reference() -> None:
    # returns: +0.02, -0.02, +0.02, -0.02 (population stdev of these = 0.02)
    closes = [100.0, 102.0, 99.96, 101.9592, 99.920016]
    assert realized_volatility(closes) == pytest.approx(0.02, abs=1e-4)


def test_realized_volatility_zero_for_flat_prices() -> None:
    assert realized_volatility([100.0, 100.0, 100.0]) == 0.0


def test_realized_volatility_raises_when_insufficient_closes() -> None:
    with pytest.raises(InsufficientDataError):
        realized_volatility([100.0])
