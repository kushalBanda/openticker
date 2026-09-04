from pathlib import Path
from typing import Final

API_PREFIX_BACKTEST: Final = "/backtests"
API_PREFIX_PORTFOLIO: Final = "/portfolio"
API_PREFIX_MARKET: Final = "/market"

DEFAULT_INTERVAL: Final = "1d"

PROVIDERS_CONFIG_PATH: Final = Path("packages/ingest/config/providers.yaml")
