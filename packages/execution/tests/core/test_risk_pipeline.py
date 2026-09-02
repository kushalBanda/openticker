from datetime import UTC, datetime

from execution.core.interfaces import RiskResult
from execution.core.risk_pipeline import RiskPipeline
from execution.risk_checks.max_position_size import (
    MaxPositionSizeCheck,  # noqa: F401  self-registers
)
from strategy.core.constants import ORDER_SIDE_BUY, ORDER_TYPE_MARKET
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio


def _order(quantity: int = 10) -> Order:
    return Order(
        symbol="NSE-RELIANCE",
        side=ORDER_SIDE_BUY,
        quantity=quantity,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )


class _AlwaysPass:
    def __init__(self) -> None:
        self.called = False

    def check(self, order: Order, portfolio: Portfolio, reference_price: float) -> RiskResult:
        self.called = True
        return RiskResult(passed=True)


class _AlwaysReject:
    def __init__(self) -> None:
        self.called = False

    def check(self, order: Order, portfolio: Portfolio, reference_price: float) -> RiskResult:
        self.called = True
        return RiskResult(passed=False, reason="rejected by test double")


def test_pipeline_passes_when_all_checks_pass() -> None:
    pipeline = RiskPipeline([_AlwaysPass(), _AlwaysPass()])
    portfolio = Portfolio(starting_cash=100_000.0)

    result = pipeline.check(_order(), portfolio, 100.0)

    assert result.passed is True


def test_pipeline_short_circuits_on_first_rejection() -> None:
    first = _AlwaysReject()
    second = _AlwaysPass()
    pipeline = RiskPipeline([first, second])
    portfolio = Portfolio(starting_cash=100_000.0)

    result = pipeline.check(_order(), portfolio, 100.0)

    assert result.passed is False
    assert first.called is True
    assert second.called is False


def test_from_config_builds_pipeline_in_declared_order() -> None:
    config = {
        "checks": [
            {"name": "max_position_size", "params": {"max_shares_per_symbol": 5}},
        ]
    }
    pipeline = RiskPipeline.from_config(config)
    portfolio = Portfolio(starting_cash=100_000.0)

    result = pipeline.check(_order(quantity=50), portfolio, 100.0)

    assert result.passed is False
