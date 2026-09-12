from typing import Final

SERVER_NAME: Final = "quant-engine"
TOOL_EVALUATE_SIGNAL: Final = "evaluate_signal"
TOOL_CONNECT_ADAPTER: Final = "connect_adapter"
TOOL_FETCH_BARS: Final = "fetch_bars"
TOOL_RUN_BACKTEST: Final = "run_backtest"

# run_backtest's cost_profile auto-selection: bars at this interval are
# treated as delivery-style holds (no same-day round trip), anything
# shorter is treated as intraday, matching Kite/Groww's own fee schedules.
DELIVERY_INTERVAL: Final = "1d"
COST_SEGMENT_DELIVERY: Final = "delivery"
COST_SEGMENT_INTRADAY: Final = "intraday"
COST_PROFILE_FREE: Final = "free"
COST_PROFILE_MANUAL: Final = "manual"
