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
