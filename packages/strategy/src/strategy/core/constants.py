from typing import Final

ORDER_SIDE_BUY: Final = "buy"
ORDER_SIDE_SELL: Final = "sell"

ORDER_TYPE_MARKET: Final = "market"

ORDER_STATUS_PENDING: Final = "pending"
# Written before the order is handed to a real broker's API (PaperBroker/
# LiveBroker only - BacktestBroker has no submission round-trip, it goes
# straight to PENDING). This is the write-ahead row a crash-recovery
# reconciliation pass looks for on restart, see docs/designs/
# trading-bot-first-pivot.md's "Order Lifecycle Design".
ORDER_STATUS_SUBMITTING: Final = "submitting"
ORDER_STATUS_OPEN: Final = "open"
ORDER_STATUS_PARTIALLY_FILLED: Final = "partially_filled"
ORDER_STATUS_FILLED: Final = "filled"
ORDER_STATUS_CANCELLED: Final = "cancelled"
ORDER_STATUS_REJECTED: Final = "rejected"
# Transient status a restarted PaperBroker/LiveBroker assigns to any order
# not already in a terminal state, until it is confirmed against the
# broker's own order book.
ORDER_STATUS_RECONCILING: Final = "reconciling"

DEFAULT_STARTING_CASH: Final = 100_000.0
DEFAULT_SLIPPAGE_BPS: Final = 0.0
DEFAULT_COMMISSION_PER_SHARE: Final = 0.0

TABLE_LEDGER_ENTRIES: Final = "ledger_entries"
TABLE_EQUITY_CURVE_POINTS: Final = "equity_curve_points"
TABLE_ORDERS: Final = "orders"

# statistics.py's sharpe_ratio needs at least 2 valid returns, which needs
# at least 3 closes.
MIN_EQUITY_POINTS_FOR_FULL_REPORT: Final = 3
