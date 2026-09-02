from datetime import UTC, datetime

from execution.risk_checks.price_collar import PriceCollarCheck
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


def test_first_observation_always_passes() -> None:
    check = PriceCollarCheck(max_deviation_pct=0.05)
    portfolio = Portfolio(starting_cash=100_000.0)

    result = check.check(_order(), portfolio, reference_price=100.0)

    assert result.passed is True


def test_rejects_order_priced_too_far_from_last_trade() -> None:
    check = PriceCollarCheck(max_deviation_pct=0.05)
    portfolio = Portfolio(starting_cash=100_000.0)
    check.check(_order(), portfolio, reference_price=100.0)

    result = check.check(_order(), portfolio, reference_price=120.0)

    assert result.passed is False


def test_passes_when_move_is_within_collar() -> None:
    check = PriceCollarCheck(max_deviation_pct=0.05)
    portfolio = Portfolio(starting_cash=100_000.0)
    check.check(_order(), portfolio, reference_price=100.0)

    result = check.check(_order(), portfolio, reference_price=102.0)

    assert result.passed is True
