from strategy.core.models import Order
from strategy.core.portfolio import Portfolio

from execution.core.constants import RISK_CHECK_MAX_ORDER_NOTIONAL
from execution.core.interfaces import RiskResult
from execution.core.registry import register_risk_check


@register_risk_check(RISK_CHECK_MAX_ORDER_NOTIONAL)
class MaxOrderNotionalCheck:
    def __init__(self, max_notional: float) -> None:
        if max_notional <= 0:
            raise ValueError("max_notional must be positive")
        self._max_notional = max_notional

    def check(self, order: Order, portfolio: Portfolio, reference_price: float) -> RiskResult:
        notional = order.quantity * reference_price
        if notional > self._max_notional:
            return RiskResult(
                passed=False,
                reason=(
                    f"order notional {notional:.2f} exceeds max {self._max_notional:.2f}"
                ),
            )
        return RiskResult(passed=True)
