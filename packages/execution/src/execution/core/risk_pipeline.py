from typing import Any

from strategy.core.models import Order
from strategy.core.portfolio import Portfolio

from execution.core.interfaces import RiskCheck, RiskResult
from execution.core.registry import RiskCheckFactory

_PASS: RiskResult = RiskResult(passed=True)


class RiskPipeline:
    def __init__(self, checks: list[RiskCheck]) -> None:
        self._checks = checks

    def check(self, order: Order, portfolio: Portfolio, reference_price: float) -> RiskResult:
        for risk_check in self._checks:
            result = risk_check.check(order, portfolio, reference_price)
            if not result.passed:
                return result
        return _PASS

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "RiskPipeline":
        checks = [
            RiskCheckFactory.create(entry["name"], entry.get("params", {}))
            for entry in config["checks"]
        ]
        return cls(checks)
