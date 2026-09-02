from strategy.core.models import Order
from strategy.core.portfolio import Portfolio

from execution.core.constants import RISK_CHECK_PRICE_COLLAR
from execution.core.interfaces import RiskResult
from execution.core.registry import register_risk_check


@register_risk_check(RISK_CHECK_PRICE_COLLAR)
class PriceCollarCheck:
    """Rejects an order if reference_price has moved more than
    max_deviation_pct since the last price this check observed for that
    symbol — a stale/erratic-quote guard. Orders here carry no limit
    price of their own (market orders only), so the collar compares
    consecutive market references rather than an order price to a quote.
    First observation for a symbol always passes and sets the baseline.
    """

    def __init__(self, max_deviation_pct: float) -> None:
        if not (0 < max_deviation_pct <= 1):
            raise ValueError("max_deviation_pct must be in (0, 1]")
        self._max_deviation_pct = max_deviation_pct
        self._last_price_by_symbol: dict[str, float] = {}

    def check(self, order: Order, portfolio: Portfolio, reference_price: float) -> RiskResult:
        last_price = self._last_price_by_symbol.get(order.symbol)
        self._last_price_by_symbol[order.symbol] = reference_price

        if last_price is None:
            return RiskResult(passed=True)

        deviation = abs(reference_price - last_price) / last_price
        if deviation > self._max_deviation_pct:
            return RiskResult(
                passed=False,
                reason=(
                    f"reference price moved {deviation:.2%} for {order.symbol}, "
                    f"exceeds collar {self._max_deviation_pct:.2%}"
                ),
            )
        return RiskResult(passed=True)
