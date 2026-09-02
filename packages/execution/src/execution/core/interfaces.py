from dataclasses import dataclass
from typing import Protocol

from strategy.core.models import Order
from strategy.core.portfolio import Portfolio


@dataclass(frozen=True)
class RiskResult:
    passed: bool
    reason: str | None = None  # populated only when passed is False


class RiskCheck(Protocol):
    def check(self, order: Order, portfolio: Portfolio) -> RiskResult: ...
