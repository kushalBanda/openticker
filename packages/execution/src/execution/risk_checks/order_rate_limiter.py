import time
from collections import deque
from collections.abc import Callable

from strategy.core.models import Order
from strategy.core.portfolio import Portfolio

from execution.core.constants import RISK_CHECK_ORDER_RATE_LIMITER
from execution.core.interfaces import RiskResult
from execution.core.registry import register_risk_check


@register_risk_check(RISK_CHECK_ORDER_RATE_LIMITER)
class OrderRateLimiterCheck:
    """Token-bucket style limiter sized to Kite's documented order-rate
    caps (default: 10/second). clock is injectable for deterministic tests.
    """

    def __init__(
        self,
        max_orders_per_second: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_orders_per_second <= 0:
            raise ValueError("max_orders_per_second must be positive")
        self._max_orders_per_second = max_orders_per_second
        self._clock = clock
        self._timestamps: deque[float] = deque()

    def check(self, order: Order, portfolio: Portfolio, reference_price: float) -> RiskResult:
        now = self._clock()
        while self._timestamps and now - self._timestamps[0] >= 1.0:
            self._timestamps.popleft()

        if len(self._timestamps) >= self._max_orders_per_second:
            return RiskResult(
                passed=False,
                reason=(
                    f"order rate limit exceeded: {self._max_orders_per_second}/second"
                ),
            )

        self._timestamps.append(now)
        return RiskResult(passed=True)
