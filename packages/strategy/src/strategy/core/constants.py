from typing import Final

ORDER_SIDE_BUY: Final = "buy"
ORDER_SIDE_SELL: Final = "sell"

ORDER_TYPE_MARKET: Final = "market"

ORDER_STATUS_PENDING: Final = "pending"
ORDER_STATUS_OPEN: Final = "open"
ORDER_STATUS_PARTIALLY_FILLED: Final = "partially_filled"
ORDER_STATUS_FILLED: Final = "filled"
ORDER_STATUS_CANCELLED: Final = "cancelled"
ORDER_STATUS_REJECTED: Final = "rejected"

DEFAULT_STARTING_CASH: Final = 100_000.0
DEFAULT_SLIPPAGE_BPS: Final = 0.0
DEFAULT_COMMISSION_PER_SHARE: Final = 0.0

TABLE_LEDGER_ENTRIES: Final = "ledger_entries"
TABLE_EQUITY_CURVE_POINTS: Final = "equity_curve_points"
TABLE_RUNS: Final = "runs"

# statistics.py's sharpe_ratio needs at least 2 valid returns, which needs
# at least 3 closes.
MIN_EQUITY_POINTS_FOR_FULL_REPORT: Final = 3
