from pathlib import Path
from typing import Final

PROVIDER_KITE: Final = "kite"
PROVIDER_GROWW: Final = "groww"

CANONICAL_INTERVALS: Final[tuple[str, ...]] = ("1m", "3m", "5m", "10m", "15m", "30m", "60m", "1d")

DEFAULT_DB_PATH: Final = Path("data/quant.duckdb")
TABLE_BARS: Final = "bars"
TABLE_TICKS: Final = "ticks"

KITE_HISTORICAL_REQUESTS_PER_SECOND: Final = 3.0
GROWW_NON_TRADING_REQUESTS_PER_SECOND: Final = 20.0

INSTRUMENT_MASTER_REFRESH_HOURS: Final = 24

KITE_BASE_URL: Final = "https://api.kite.trade"
KITE_API_VERSION: Final = "3"


def kite_auth_headers(api_key: str, access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {api_key}:{access_token}",
        "X-Kite-Version": KITE_API_VERSION,
    }
