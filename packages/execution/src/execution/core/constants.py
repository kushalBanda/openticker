from typing import Final

# Order lifecycle states, matching strategy.core.constants' ORDER_STATUS_*
# values (imported there, not redefined here — this package's state
# machine operates on those same string constants).

RISK_CHECK_MAX_POSITION_SIZE: Final = "max_position_size"
RISK_CHECK_MAX_ORDER_NOTIONAL: Final = "max_order_notional"
RISK_CHECK_MAX_DAILY_LOSS: Final = "max_daily_loss"
RISK_CHECK_ORDER_RATE_LIMITER: Final = "order_rate_limiter"
RISK_CHECK_PRICE_COLLAR: Final = "price_collar"
RISK_CHECK_DUPLICATE_ORDER: Final = "duplicate_order"

# Generic interval-name -> minutes table, used by TickBarAggregator to
# compute bucket boundaries from a tick timestamp. Deliberately not the
# same thing as a provider's own interval map (e.g.
# ingest.adapters.kite.intervals' KITE_INTERVAL_MAP, which translates to
# Kite's own interval strings) — this is purely "how many minutes wide is
# one bar," and has no provider-specific meaning.
INTERVAL_MINUTES: Final[dict[str, int]] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
    "60m": 60,
    "1d": 24 * 60,
}
