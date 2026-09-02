from datetime import UTC, datetime

from execution.risk_checks.order_rate_limiter import OrderRateLimiterCheck
from strategy.core.constants import ORDER_SIDE_BUY, ORDER_TYPE_MARKET
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio


def _order() -> Order:
    return Order(
        symbol="NSE-RELIANCE",
        side=ORDER_SIDE_BUY,
        quantity=1,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_rejects_order_exceeding_per_second_rate() -> None:
    fake_now = [0.0]
    check = OrderRateLimiterCheck(max_orders_per_second=2, clock=lambda: fake_now[0])
    portfolio = Portfolio(starting_cash=100_000.0)

    first = check.check(_order(), portfolio, reference_price=100.0)
    second = check.check(_order(), portfolio, reference_price=100.0)
    third = check.check(_order(), portfolio, reference_price=100.0)

    assert first.passed is True
    assert second.passed is True
    assert third.passed is False


def test_allows_orders_again_after_the_window_elapses() -> None:
    fake_now = [0.0]
    check = OrderRateLimiterCheck(max_orders_per_second=1, clock=lambda: fake_now[0])
    portfolio = Portfolio(starting_cash=100_000.0)

    check.check(_order(), portfolio, reference_price=100.0)
    fake_now[0] = 1.5
    result = check.check(_order(), portfolio, reference_price=100.0)

    assert result.passed is True
