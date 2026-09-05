from pathlib import Path
from typing import Final

PROVIDER_KITE: Final = "kite"
PROVIDER_GROWW: Final = "groww"

CANONICAL_INTERVALS: Final[tuple[str, ...]] = (
    "1m",
    "3m",
    "5m",
    "10m",
    "15m",
    "30m",
    "60m",
    "1d",
)

DEFAULT_DB_PATH: Final = Path("data/quant.duckdb")
TABLE_BARS: Final = "bars"
TABLE_TICKS: Final = "ticks"
TABLE_INDEX_CONSTITUENTS: Final = "index_constituents"

INDEX_NIFTY50: Final = "NIFTY50"
INDEX_NIFTY500: Final = "NIFTY500"
INDEX_NIFTY_MIDCAP150: Final = "NIFTY_MIDCAP150"
INDEX_NIFTY_SMALLCAP250: Final = "NIFTY_SMALLCAP250"

KNOWN_INDICES: Final[tuple[str, ...]] = (
    INDEX_NIFTY50,
    INDEX_NIFTY500,
    INDEX_NIFTY_MIDCAP150,
    INDEX_NIFTY_SMALLCAP250,
)

# NSE only publishes current constituents, no historical-by-year snapshots,
# so each fetch is always tagged with the current year, never a past one.
NSE_INDEX_CSV_URLS: Final[dict[str, str]] = {
    INDEX_NIFTY50: "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    INDEX_NIFTY500: "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
    INDEX_NIFTY_MIDCAP150: (
        "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv"
    ),
    INDEX_NIFTY_SMALLCAP250: (
        "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv"
    ),
}

NSE_WARMUP_URL: Final = "https://www.nseindia.com"
NSE_USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

SOURCE_NSE_CSV: Final = "nse_csv"

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
