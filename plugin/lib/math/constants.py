"""Shared numeric constants for plugin/lib/math.

Ported from quant.core.constants, trimmed to the constants a skill
script still needs (signal storage table names are dropped, nothing
under plugin/lib writes a signals/forecasts/watchlist table).
"""

from typing import Final

FORECAST_SCALE_MAX: Final = 20.0
FORECAST_SCALE_MIN: Final = -20.0

ORDER_SIDE_BUY: Final = "buy"
ORDER_SIDE_SELL: Final = "sell"
ORDER_STATUS_PENDING: Final = "pending"
ORDER_TYPE_MARKET: Final = "market"

DEFAULT_SLIPPAGE_BPS: Final = 0.0
DEFAULT_COMMISSION_PER_SHARE: Final = 0.0

RSI_MIDPOINT: Final = 50.0

# Observation-frequency annualization factors, bucketed by the average
# number of calendar days between consecutive observations.
ANNUALIZATION_FACTOR_DAILY: Final = 252
ANNUALIZATION_FACTOR_WEEKLY: Final = 52
ANNUALIZATION_FACTOR_SEMI_MONTHLY: Final = 26
ANNUALIZATION_FACTOR_MONTHLY: Final = 12
ANNUALIZATION_FACTOR_QUARTERLY: Final = 4
ANNUALIZATION_FACTOR_ANNUALLY: Final = 1

# Actual/365.25 day-count convention for compounding annualization: real
# elapsed calendar time, not an assumed bar cadence.
CALENDAR_DAYS_PER_YEAR: Final = 365.25

# Actual/360 day-count convention for the risk-free rate drag applied to
# excess returns, standard money-market convention.
RISK_FREE_RATE_DAY_COUNT_DIVISOR: Final = 360.0

# Minimum (signal, forward return) pairs for a usable IC read.
MIN_SAMPLE_SIZE: Final = 30

OVERLAPPING_WINDOWS_CAVEAT: Final = (
    "information_coefficient/ic_p_value are computed on overlapping "
    "N-day forward-return windows; consecutive samples share most of "
    "their days and are not independent, so ic_p_value understates the "
    "true uncertainty. effective_ic_p_value, computed on a "
    "non-overlapping subsample of effective_sample_size points, is the "
    "more honest number to judge significance against."
)
