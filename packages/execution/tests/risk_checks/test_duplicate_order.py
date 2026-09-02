from datetime import UTC, datetime

from execution.risk_checks.duplicate_order import DuplicateOrderCheck
from strategy.core.constants import ORDER_SIDE_BUY, ORDER_TYPE_MARKET
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio


def _order() -> Order:
    return Order(
        symbol="NSE-RELIANCE",
        side=ORDER_SIDE_BUY,
        quantity=10,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_rejects_resubmission_of_order_already_in_flight() -> None:
    check = DuplicateOrderCheck()
    portfolio = Portfolio(starting_cash=100_000.0)
    order = _order()

    first = check.check(order, portfolio, reference_price=100.0)
    second = check.check(order, portfolio, reference_price=100.0)

    assert first.passed is True
    assert second.passed is False


def test_allows_resubmission_after_mark_resolved() -> None:
    check = DuplicateOrderCheck()
    portfolio = Portfolio(starting_cash=100_000.0)
    order = _order()

    check.check(order, portfolio, reference_price=100.0)
    check.mark_resolved(order)
    result = check.check(order, portfolio, reference_price=100.0)

    assert result.passed is True
