from data_engine.core.constants import PROVIDER_GROWW
from data_engine.core.intervals import register_interval_map

GROWW_INTERVAL_MAP: dict[str, str | int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
    "60m": 60,
    "1d": "day",
}

register_interval_map(PROVIDER_GROWW, GROWW_INTERVAL_MAP)
