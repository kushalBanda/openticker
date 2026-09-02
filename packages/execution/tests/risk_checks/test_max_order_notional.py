from datetime import UTC, datetime

from execution.risk_checks.max_order_notional import MaxOrderNotionalCheck
from strategy.core.constants import ORDER_SIDE_BUY, ORDER_TYPE_MARKET
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio


def _order(quantity: int) -> Order:
    return Order(
        symbol="NSE-RELIANCE",
        side=ORDER_SIDE_BUY,
        quantity=quantity,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_rejects_order_exceeding_notional_cap() -> None:
    check = MaxOrderNotionalCheck(max_notional=1000.0)
    portfolio = Portfolio(starting_cash=100_000.0)

    result = check.check(_order(quantity=20), portfolio, reference_price=100.0)

    assert result.passed is False


def test_passes_order_within_notional_cap() -> None:
    check = MaxOrderNotionalCheck(max_notional=5000.0)
    portfolio = Portfolio(starting_cash=100_000.0)

    result = check.check(_order(quantity=20), portfolio, reference_price=100.0)

    assert result.passed is True
