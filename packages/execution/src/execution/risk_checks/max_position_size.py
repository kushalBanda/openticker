from strategy.core.constants import ORDER_SIDE_BUY
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio

from execution.core.constants import RISK_CHECK_MAX_POSITION_SIZE
from execution.core.interfaces import RiskResult
from execution.core.registry import register_risk_check


@register_risk_check(RISK_CHECK_MAX_POSITION_SIZE)
class MaxPositionSizeCheck:
    def __init__(self, max_shares_per_symbol: int) -> None:
        if max_shares_per_symbol <= 0:
            raise ValueError("max_shares_per_symbol must be positive")
        self._max_shares_per_symbol = max_shares_per_symbol

    def check(self, order: Order, portfolio: Portfolio) -> RiskResult:
        current = portfolio.positions.get(order.symbol, 0)
        delta = order.quantity if order.side == ORDER_SIDE_BUY else -order.quantity
        resulting = abs(current + delta)

        if resulting > self._max_shares_per_symbol:
            return RiskResult(
                passed=False,
                reason=(
                    f"order would take {order.symbol} position to {resulting} shares, "
                    f"exceeds max {self._max_shares_per_symbol}"
                ),
            )
        return RiskResult(passed=True)
