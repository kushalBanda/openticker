from typing import Final

API_PREFIX_BACKTEST: Final = "/backtests"
API_PREFIX_PORTFOLIO: Final = "/portfolio"
API_PREFIX_MARKET: Final = "/market"
API_PREFIX_AUTH: Final = "/auth"

DEFAULT_INTERVAL: Final = "1d"

# Default litellm model string for PairsTradingRequest's optional AI advisor.
DEFAULT_ADVISOR_MODEL: Final = "nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b"

DEFAULT_PAGE: Final = 1
DEFAULT_PAGE_SIZE: Final = 20
MAX_PAGE_SIZE: Final = 100

JWT_ALGORITHM: Final = "HS256"
JWT_EXPIRY_SECONDS: Final = 24 * 60 * 60
