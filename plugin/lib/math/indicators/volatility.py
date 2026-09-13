"""Volatility indicators: Bollinger Bands and ATR wrap `ta.volatility`;
realized volatility is hand-rolled since ta has no annualized-volatility
function, reusing ta.others.DailyReturnIndicator for the return series.
"""

from dataclasses import dataclass

from ta.others import DailyReturnIndicator
from ta.volatility import AverageTrueRange, BollingerBands

from lib.math.exceptions import InsufficientDataError
from lib.math.indicators._common import (
    DEFAULT_TRAILING_COUNT,
    TrailingReading,
    _trailing_reading,
)
from lib.math.series import (
    bar_closes_to_series,
    bar_highs_to_series,
    bar_lows_to_series,
)
from lib.mechanics.models import Bar


@dataclass(frozen=True)
class BollingerReading:
    upper: float
    middle: float
    lower: float


def compute_bollinger_bands(bars: list[Bar], window: int = 20, window_dev: int = 2, trailing_count: int = DEFAULT_TRAILING_COUNT) -> BollingerReading:
    if len(bars) < window:
        raise InsufficientDataError(f"compute_bollinger_bands needs at least {window} bars, got {len(bars)}")
    indicator = BollingerBands(close=bar_closes_to_series(bars), window=window, window_dev=window_dev)
    return BollingerReading(
        upper=_trailing_reading(indicator.bollinger_hband(), 1).latest,
        middle=_trailing_reading(indicator.bollinger_mavg(), 1).latest,
        lower=_trailing_reading(indicator.bollinger_lband(), 1).latest,
    )


def compute_atr(bars: list[Bar], window: int = 14, trailing_count: int = DEFAULT_TRAILING_COUNT) -> TrailingReading:
    if len(bars) < window + 1:
        raise InsufficientDataError(f"compute_atr needs at least {window + 1} bars, got {len(bars)}")
    series = AverageTrueRange(high=bar_highs_to_series(bars), low=bar_lows_to_series(bars), close=bar_closes_to_series(bars), window=window).average_true_range()
    return _trailing_reading(series, trailing_count)


def compute_realized_volatility(bars: list[Bar], window: int = 20, annualization_factor: int = 252) -> float:
    if len(bars) < window + 1:
        raise InsufficientDataError(f"compute_realized_volatility needs at least {window + 1} bars, got {len(bars)}")
    closes = bar_closes_to_series(bars)
    returns = DailyReturnIndicator(close=closes).daily_return().dropna().iloc[-window:] / 100
    mean = returns.mean()
    variance = ((returns - mean) ** 2).sum() / (len(returns) - 1) if len(returns) > 1 else 0.0
    std = variance ** 0.5
    return float(std * (annualization_factor ** 0.5) * 100)
