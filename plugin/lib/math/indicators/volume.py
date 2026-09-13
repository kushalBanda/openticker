"""Volume indicators: OBV and Accumulation/Distribution wrap
`ta.volume`. Above-average volume and VWAP stay hand-rolled - ta has no
per-bar volume-ratio function, and ta's VWAP is a fixed-window rolling
average, a different concept from this repo's session-anchored VWAP
over exactly the bars the caller passes in.
"""

from ta.volume import AccDistIndexIndicator, OnBalanceVolumeIndicator

from lib.math.exceptions import InsufficientDataError
from lib.math.series import (
    bar_closes_to_series,
    bar_highs_to_series,
    bar_lows_to_series,
    bar_volumes_to_series,
)
from lib.mechanics.models import Bar


def compute_above_average_volume(bars: list[Bar], window: int = 20) -> float:
    if len(bars) < window:
        raise InsufficientDataError(f"compute_above_average_volume needs at least {window} bars, got {len(bars)}")
    recent = bars[-window:]
    avg_volume = sum(b.volume for b in recent) / window
    if avg_volume == 0:
        return 0.0
    return bars[-1].volume / avg_volume


def compute_obv(bars: list[Bar]) -> float:
    if len(bars) < 2:
        raise InsufficientDataError(f"compute_obv needs at least 2 bars, got {len(bars)}")
    series = OnBalanceVolumeIndicator(close=bar_closes_to_series(bars), volume=bar_volumes_to_series(bars)).on_balance_volume()
    return float(series.iloc[-1])


def compute_vwap(bars: list[Bar]) -> float:
    if not bars:
        raise InsufficientDataError("compute_vwap needs at least 1 bar, got 0")
    total_volume = sum(b.volume for b in bars)
    if total_volume == 0:
        raise ValueError("cannot compute VWAP with zero total volume")
    weighted_sum = sum(((b.high + b.low + b.close) / 3) * b.volume for b in bars)
    return weighted_sum / total_volume


def compute_accumulation_distribution(bars: list[Bar]) -> float:
    if not bars:
        raise InsufficientDataError("compute_accumulation_distribution needs at least 1 bar, got 0")
    series = AccDistIndexIndicator(
        high=bar_highs_to_series(bars), low=bar_lows_to_series(bars),
        close=bar_closes_to_series(bars), volume=bar_volumes_to_series(bars),
    ).acc_dist_index()
    return float(series.iloc[-1])
