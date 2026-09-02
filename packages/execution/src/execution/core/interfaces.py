from dataclasses import dataclass
from typing import Protocol

from strategy.core.models import Order
from strategy.core.portfolio import Portfolio


@dataclass(frozen=True)
class RiskResult:
    passed: bool
    reason: str | None = None  # populated only when passed is False


class RiskCheck(Protocol):
    def check(self, order: Order, portfolio: Portfolio, reference_price: float) -> RiskResult: ...
    # reference_price is the latest known market price for order.symbol —
    # Order carries no price (market orders), so notional/collar checks
    # need it passed in explicitly rather than reading it off the order.
