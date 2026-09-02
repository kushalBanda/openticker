from strategy.core.models import Order
from strategy.core.portfolio import Portfolio

from execution.core.constants import RISK_CHECK_DUPLICATE_ORDER
from execution.core.interfaces import RiskResult
from execution.core.registry import register_risk_check

_Signature = tuple[str, str, int, str]


def _signature(order: Order) -> _Signature:
    return (order.symbol, order.side, order.quantity, order.placed_at_ts.isoformat())


@register_risk_check(RISK_CHECK_DUPLICATE_ORDER)
class DuplicateOrderCheck:
    """Rejects a resubmission of an order already in flight (same symbol,
    side, quantity, and placed_at_ts — Order carries no id of its own).
    The caller must call mark_resolved(order) once an order reaches a
    terminal state (FILLED/CANCELLED/REJECTED) so its signature can be
    submitted again later without being treated as a duplicate.
    """

    def __init__(self) -> None:
        self._in_flight: set[_Signature] = set()

    def mark_resolved(self, order: Order) -> None:
        self._in_flight.discard(_signature(order))

    def check(self, order: Order, portfolio: Portfolio, reference_price: float) -> RiskResult:
        signature = _signature(order)
        if signature in self._in_flight:
            return RiskResult(
                passed=False,
                reason=f"duplicate order already in flight for {order.symbol}",
            )
        self._in_flight.add(signature)
        return RiskResult(passed=True)
