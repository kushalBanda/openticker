from datetime import UTC, datetime, timedelta

from lib.math.indicators import compute_rsi, compute_sma, scale_rsi
from lib.math.types import RawSignal
from lib.mechanics.models import Bar


def _bars(closes: list[float]) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Bar(
            symbol="X", interval="1d", ts=start + timedelta(days=i),
            open=c, high=c, low=c, close=c, volume=1000, provider="kite",
        )
        for i, c in enumerate(closes)
    ]


def test_compute_sma_matches_plain_mean_over_window() -> None:
    bars = _bars([10.0, 20.0, 30.0])
    raw = compute_sma(bars, window=3)
    assert raw.value == 20.0


def test_compute_rsi_is_bounded_0_to_100() -> None:
    bars = _bars([float(i) for i in range(1, 40)])
    raw = compute_rsi(bars, period=14)
    assert 0.0 <= raw.value <= 100.0
    assert raw.value > 50.0


def test_scale_rsi_maps_midpoint_to_zero() -> None:
    raw = RawSignal(symbol="X", interval="1d", ts=datetime(2026, 1, 1, tzinfo=UTC), name="rsi", value=50.0)
    forecast = scale_rsi(raw)
    assert forecast.scaled_value == 0.0
