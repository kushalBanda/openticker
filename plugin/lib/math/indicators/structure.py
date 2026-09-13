"""Price-structure indicators: breakout, support/resistance, candlestick
patterns, gap, 52-week range position, classic pivot points. Every
threshold is a keyword parameter with a default.
"""

from dataclasses import dataclass

from lib.math.exceptions import InsufficientDataError
from lib.mechanics.models import Bar


@dataclass(frozen=True)
class BreakoutReading:
    direction: str
    level: float
    breakout_pct: float


@dataclass(frozen=True)
class SupportResistanceReading:
    support: float
    resistance: float


@dataclass(frozen=True)
class CandlestickReading:
    pattern: str
    strength: float


@dataclass(frozen=True)
class GapReading:
    gap_pct: float
    direction: str


@dataclass(frozen=True)
class PivotPointsReading:
    pivot: float
    r1: float
    r2: float
    r3: float
    s1: float
    s2: float
    s3: float


def compute_breakout(bars: list[Bar], lookback: int = 20) -> BreakoutReading:
    if len(bars) < lookback + 1:
        raise InsufficientDataError(f"compute_breakout needs at least {lookback + 1} bars, got {len(bars)}")
    prior = bars[-(lookback + 1): -1]
    last = bars[-1]
    range_high = max(b.high for b in prior)
    range_low = min(b.low for b in prior)
    if last.close > range_high:
        return BreakoutReading("up", range_high, (last.close - range_high) / range_high * 100)
    if last.close < range_low:
        return BreakoutReading("down", range_low, (range_low - last.close) / range_low * 100)
    return BreakoutReading("none", range_high, 0.0)


def compute_support_resistance(bars: list[Bar], lookback: int = 20) -> SupportResistanceReading:
    if len(bars) < lookback:
        raise InsufficientDataError(f"compute_support_resistance needs at least {lookback} bars, got {len(bars)}")
    window = bars[-lookback:]
    return SupportResistanceReading(support=min(b.low for b in window), resistance=max(b.high for b in window))


def compute_candlestick_pattern(
    bars: list[Bar],
    doji_body_to_range_max: float = 0.1,
    hammer_wick_to_body_min: float = 2.0,
    hammer_opposite_wick_to_body_max: float = 0.3,
) -> CandlestickReading:
    if len(bars) < 2:
        raise InsufficientDataError(f"compute_candlestick_pattern needs at least 2 bars, got {len(bars)}")
    prev, last = bars[-2], bars[-1]
    body = abs(last.close - last.open)
    bar_range = last.high - last.low
    if bar_range == 0:
        return CandlestickReading("none", 0.0)
    upper_wick = last.high - max(last.open, last.close)
    lower_wick = min(last.open, last.close) - last.low

    prev_bearish = prev.close < prev.open
    prev_bullish = prev.close > prev.open
    last_bullish = last.close > last.open
    last_bearish = last.close < last.open

    if prev_bearish and last_bullish and last.open <= prev.close and last.close >= prev.open:
        return CandlestickReading("bullish_engulfing", body / bar_range)
    if prev_bullish and last_bearish and last.open >= prev.close and last.close <= prev.open:
        return CandlestickReading("bearish_engulfing", body / bar_range)
    if body / bar_range <= doji_body_to_range_max:
        return CandlestickReading("doji", 1 - body / bar_range)
    if body > 0 and lower_wick >= hammer_wick_to_body_min * body and upper_wick <= hammer_opposite_wick_to_body_max * body:
        return CandlestickReading("hammer", lower_wick / bar_range)
    if body > 0 and upper_wick >= hammer_wick_to_body_min * body and lower_wick <= hammer_opposite_wick_to_body_max * body:
        return CandlestickReading("shooting_star", upper_wick / bar_range)
    return CandlestickReading("none", 0.0)


def compute_gap(bars: list[Bar]) -> GapReading:
    if len(bars) < 2:
        raise InsufficientDataError(f"compute_gap needs at least 2 bars, got {len(bars)}")
    prev_close = bars[-2].close
    today_open = bars[-1].open
    gap_pct = (today_open - prev_close) / prev_close * 100
    direction = "up" if gap_pct > 0 else "down" if gap_pct < 0 else "none"
    return GapReading(gap_pct=gap_pct, direction=direction)


def compute_52_week_range_position(bars: list[Bar], lookback_bars: int = 252) -> float:
    if len(bars) < lookback_bars:
        raise InsufficientDataError(f"compute_52_week_range_position needs at least {lookback_bars} bars, got {len(bars)}")
    window = bars[-lookback_bars:]
    lowest = min(b.low for b in window)
    highest = max(b.high for b in window)
    if highest == lowest:
        return 50.0
    return (bars[-1].close - lowest) / (highest - lowest) * 100


def compute_pivot_points(bars: list[Bar]) -> PivotPointsReading:
    if len(bars) < 2:
        raise InsufficientDataError(f"compute_pivot_points needs at least 2 bars, got {len(bars)}")
    prev = bars[-2]
    pivot = (prev.high + prev.low + prev.close) / 3
    return PivotPointsReading(
        pivot=pivot,
        r1=2 * pivot - prev.low,
        s1=2 * pivot - prev.high,
        r2=pivot + (prev.high - prev.low),
        s2=pivot - (prev.high - prev.low),
        r3=prev.high + 2 * (pivot - prev.low),
        s3=prev.low - 2 * (prev.high - pivot),
    )
