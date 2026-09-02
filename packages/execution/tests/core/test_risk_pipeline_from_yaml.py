from datetime import UTC, datetime
from pathlib import Path

import yaml
from execution.core.risk_pipeline import RiskPipeline
from execution.risk_checks.duplicate_order import DuplicateOrderCheck  # noqa: F401
from execution.risk_checks.max_daily_loss import MaxDailyLossCheck  # noqa: F401
from execution.risk_checks.max_order_notional import MaxOrderNotionalCheck  # noqa: F401
from execution.risk_checks.max_position_size import MaxPositionSizeCheck  # noqa: F401
from execution.risk_checks.order_rate_limiter import OrderRateLimiterCheck  # noqa: F401
from execution.risk_checks.price_collar import PriceCollarCheck  # noqa: F401
from strategy.core.constants import ORDER_SIDE_BUY, ORDER_TYPE_MARKET
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio

RISK_YAML = (
    Path(__file__).resolve().parents[2] / "src" / "execution" / "config" / "risk.yaml"
)


def _order(quantity: int = 10) -> Order:
    return Order(
        symbol="NSE-RELIANCE",
        side=ORDER_SIDE_BUY,
        quantity=quantity,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_pipeline_built_from_risk_yaml_runs_all_six_checks_and_passes_a_normal_order() -> None:
    config = yaml.safe_load(RISK_YAML.read_text())
    pipeline = RiskPipeline.from_config(config)
    portfolio = Portfolio(starting_cash=100_000.0)

    result = pipeline.check(_order(quantity=10), portfolio, reference_price=1000.0)

    assert result.passed is True


def test_pipeline_built_from_risk_yaml_rejects_an_oversized_order() -> None:
    config = yaml.safe_load(RISK_YAML.read_text())
    pipeline = RiskPipeline.from_config(config)
    portfolio = Portfolio(starting_cash=100_000.0)

    result = pipeline.check(_order(quantity=10_000), portfolio, reference_price=1000.0)

    assert result.passed is False
