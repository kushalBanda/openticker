from datetime import UTC, datetime

import pytest
from quant.core.interfaces import Forecast
from quant.core.sizer import PositionSizer


def _forecast(scaled_value: float) -> Forecast:
    return Forecast(
        symbol="RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        name="rsi",
        scaled_value=scaled_value,
    )


def test_size_scales_with_conviction() -> None:
    sizer = PositionSizer(target_risk_pct=0.02)
    half_conviction = sizer.size(
        _forecast(10.0), volatility=0.02, account_equity=100_000.0, price=1000.0
    )
    full_conviction = sizer.size(
        _forecast(20.0), volatility=0.02, account_equity=100_000.0, price=1000.0
    )
    assert full_conviction.size == pytest.approx(half_conviction.size * 2)


def test_size_is_negative_for_negative_forecast() -> None:
    sizer = PositionSizer(target_risk_pct=0.02)
    result = sizer.size(
        _forecast(-15.0), volatility=0.02, account_equity=100_000.0, price=1000.0
    )
    assert result.size < 0


def test_size_scales_inversely_with_volatility() -> None:
    sizer = PositionSizer(target_risk_pct=0.02)
    low_vol = sizer.size(
        _forecast(20.0), volatility=0.01, account_equity=100_000.0, price=1000.0
    )
    high_vol = sizer.size(
        _forecast(20.0), volatility=0.04, account_equity=100_000.0, price=1000.0
    )
    assert low_vol.size == pytest.approx(high_vol.size * 4)


def test_conviction_is_clamped_to_full_risk_budget() -> None:
    # A forecast beyond +/-20 (shouldn't happen from a well-behaved Signal,
    # but the sizer must not blow past its risk cap if one ever does)
    sizer = PositionSizer(target_risk_pct=0.02)
    over_max = sizer.size(
        _forecast(40.0), volatility=0.02, account_equity=100_000.0, price=1000.0
    )
    at_max = sizer.size(
        _forecast(20.0), volatility=0.02, account_equity=100_000.0, price=1000.0
    )
    assert over_max.size == pytest.approx(at_max.size)


def test_risk_pct_reflects_actual_conviction_used() -> None:
    sizer = PositionSizer(target_risk_pct=0.02)
    result = sizer.size(
        _forecast(10.0), volatility=0.02, account_equity=100_000.0, price=1000.0
    )
    assert result.risk_pct == pytest.approx(0.01)


def test_init_raises_value_error_for_out_of_range_target_risk_pct() -> None:
    with pytest.raises(ValueError, match="target_risk_pct"):
        PositionSizer(target_risk_pct=0.0)
    with pytest.raises(ValueError, match="target_risk_pct"):
        PositionSizer(target_risk_pct=1.5)


def test_size_raises_value_error_for_non_positive_volatility() -> None:
    sizer = PositionSizer(target_risk_pct=0.02)
    with pytest.raises(ValueError, match="volatility"):
        sizer.size(_forecast(10.0), volatility=0.0, account_equity=100_000.0, price=1000.0)
