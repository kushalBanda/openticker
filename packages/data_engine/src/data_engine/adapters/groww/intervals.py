from data_engine.core.constants import PROVIDER_GROWW
from data_engine.core.intervals import register_interval_map

# Confirmed against the installed growwapi SDK's own docstring for
# get_historical_candles(candle_interval: str), examples given: "1minute",
# "5minute", "1day". The {n}minute pattern for 3/10/15/30/60 follows that
# same convention but is not individually confirmed by a live call.
GROWW_INTERVAL_MAP: dict[str, str] = {
    "1m": "1minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "60m": "60minute",
    "1d": "1day",
}

register_interval_map(PROVIDER_GROWW, GROWW_INTERVAL_MAP)
