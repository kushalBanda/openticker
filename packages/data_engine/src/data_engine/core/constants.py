from pathlib import Path
from typing import Final

PROVIDER_KITE: Final = "kite"
PROVIDER_GROWW: Final = "groww"

DEFAULT_DB_PATH: Final = Path("data/quant.duckdb")
TABLE_BARS: Final = "bars"
TABLE_TICKS: Final = "ticks"

KITE_HISTORICAL_REQUESTS_PER_SECOND: Final = 3.0
GROWW_NON_TRADING_REQUESTS_PER_SECOND: Final = 20.0

INSTRUMENT_MASTER_REFRESH_HOURS: Final = 24
