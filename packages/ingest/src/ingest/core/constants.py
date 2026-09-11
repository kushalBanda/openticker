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

DEFAULT_DB_PATH: Final = Path.home() / ".quant-plugin" / "quant.duckdb"
TABLE_BARS: Final = "bars"
TABLE_TICKS: Final = "ticks"
TABLE_INDEX_CONSTITUENTS: Final = "index_constituents"

INDEX_NIFTY50: Final = "NIFTY50"
INDEX_NIFTY500: Final = "NIFTY500"
INDEX_NIFTY_MIDCAP150: Final = "NIFTY_MIDCAP150"
INDEX_NIFTY_SMALLCAP250: Final = "NIFTY_SMALLCAP250"

INDEX_NIFTY_AUTO: Final = "NIFTY_AUTO"
INDEX_NIFTY_BANK: Final = "NIFTY_BANK"
INDEX_NIFTY_FINANCIAL_SERVICES_25_50: Final = "NIFTY_FINANCIAL_SERVICES_25_50"
INDEX_NIFTY_FMCG: Final = "NIFTY_FMCG"
INDEX_NIFTY_IT: Final = "NIFTY_IT"
INDEX_NIFTY_MEDIA: Final = "NIFTY_MEDIA"
INDEX_NIFTY_METAL: Final = "NIFTY_METAL"
INDEX_NIFTY_PHARMA: Final = "NIFTY_PHARMA"
INDEX_NIFTY_PSU_BANK: Final = "NIFTY_PSU_BANK"
INDEX_NIFTY_REALTY: Final = "NIFTY_REALTY"
INDEX_NIFTY_CONSUMER_DURABLES: Final = "NIFTY_CONSUMER_DURABLES"
INDEX_NIFTY_OIL_GAS: Final = "NIFTY_OIL_GAS"
INDEX_NIFTY_HEALTHCARE: Final = "NIFTY_HEALTHCARE"

# Sector indices confirmed to have a working NSE CSV at
# NSE_INDEX_CSV_URLS below. Several other Nifty sectoral indices
# (Private Bank, Capital Goods, Cement, Insurance, NBFC, ...) do not
# follow the same predictable ind_nifty<sector>list.csv filename and
# were left out rather than guessed at.
SECTOR_INDICES: Final[tuple[str, ...]] = (
    INDEX_NIFTY_AUTO,
    INDEX_NIFTY_BANK,
    INDEX_NIFTY_FINANCIAL_SERVICES_25_50,
    INDEX_NIFTY_FMCG,
    INDEX_NIFTY_IT,
    INDEX_NIFTY_MEDIA,
    INDEX_NIFTY_METAL,
    INDEX_NIFTY_PHARMA,
    INDEX_NIFTY_PSU_BANK,
    INDEX_NIFTY_REALTY,
    INDEX_NIFTY_CONSUMER_DURABLES,
    INDEX_NIFTY_OIL_GAS,
    INDEX_NIFTY_HEALTHCARE,
)

KNOWN_INDICES: Final[tuple[str, ...]] = (
    INDEX_NIFTY50,
    INDEX_NIFTY500,
    INDEX_NIFTY_MIDCAP150,
    INDEX_NIFTY_SMALLCAP250,
    *SECTOR_INDICES,
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
    INDEX_NIFTY_AUTO: "https://nsearchives.nseindia.com/content/indices/ind_niftyautolist.csv",
    INDEX_NIFTY_BANK: "https://nsearchives.nseindia.com/content/indices/ind_niftybanklist.csv",
    INDEX_NIFTY_FINANCIAL_SERVICES_25_50: (
        "https://nsearchives.nseindia.com/content/indices/"
        "ind_niftyfinancialservices25-50list.csv"
    ),
    INDEX_NIFTY_FMCG: "https://nsearchives.nseindia.com/content/indices/ind_niftyfmcglist.csv",
    INDEX_NIFTY_IT: "https://nsearchives.nseindia.com/content/indices/ind_niftyitlist.csv",
    INDEX_NIFTY_MEDIA: "https://nsearchives.nseindia.com/content/indices/ind_niftymedialist.csv",
    INDEX_NIFTY_METAL: "https://nsearchives.nseindia.com/content/indices/ind_niftymetallist.csv",
    INDEX_NIFTY_PHARMA: (
        "https://nsearchives.nseindia.com/content/indices/ind_niftypharmalist.csv"
    ),
    INDEX_NIFTY_PSU_BANK: (
        "https://nsearchives.nseindia.com/content/indices/ind_niftypsubanklist.csv"
    ),
    INDEX_NIFTY_REALTY: (
        "https://nsearchives.nseindia.com/content/indices/ind_niftyrealtylist.csv"
    ),
    INDEX_NIFTY_CONSUMER_DURABLES: (
        "https://nsearchives.nseindia.com/content/indices/ind_niftyconsumerdurableslist.csv"
    ),
    INDEX_NIFTY_OIL_GAS: (
        "https://nsearchives.nseindia.com/content/indices/ind_niftyoilgaslist.csv"
    ),
    INDEX_NIFTY_HEALTHCARE: (
        "https://nsearchives.nseindia.com/content/indices/ind_niftyhealthcarelist.csv"
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
