from data_engine.core.constants import PROVIDER_KITE
from data_engine.core.intervals import register_interval_map

KITE_INTERVAL_MAP: dict[str, str] = {
    "1m": "minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "60m": "60minute",
    "1d": "day",
}

register_interval_map(PROVIDER_KITE, KITE_INTERVAL_MAP)
