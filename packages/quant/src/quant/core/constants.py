from typing import Final

TABLE_SIGNALS: Final = "signals"
TABLE_FORECASTS: Final = "forecasts"

FORECAST_SCALE_MAX: Final = 20.0
FORECAST_SCALE_MIN: Final = -20.0

RSI_MIDPOINT: Final = 50.0

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
