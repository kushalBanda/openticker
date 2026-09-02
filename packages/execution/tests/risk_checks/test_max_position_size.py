from datetime import UTC, datetime

from execution.risk_checks.max_position_size import MaxPositionSizeCheck
from strategy.core.constants import ORDER_SIDE_BUY, ORDER_SIDE_SELL, ORDER_TYPE_MARKET
from strategy.core.models import Fill, Order
from strategy.core.portfolio import Portfolio


def _order(side: str, quantity: int) -> Order:
    return Order(
        symbol="NSE-RELIANCE",
        side=side,
        quantity=quantity,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_rejects_order_exceeding_max_shares_per_symbol() -> None:
    check = MaxPositionSizeCheck(max_shares_per_symbol=100)
    portfolio = Portfolio(starting_cash=100_000.0)

    result = check.check(_order(ORDER_SIDE_BUY, quantity=150), portfolio)

    assert result.passed is False
    assert result.reason is not None


def test_passes_order_within_limit() -> None:
    check = MaxPositionSizeCheck(max_shares_per_symbol=100)
    portfolio = Portfolio(starting_cash=100_000.0)

    result = check.check(_order(ORDER_SIDE_BUY, quantity=50), portfolio)

    assert result.passed is True
    assert result.reason is None


def test_considers_existing_position_before_rejecting() -> None:
    check = MaxPositionSizeCheck(max_shares_per_symbol=100)
    portfolio = Portfolio(starting_cash=100_000.0)
    portfolio.apply_fills(
        [
            Fill(
                order=_order(ORDER_SIDE_BUY, quantity=80),
                fill_price=100.0,
                fill_ts=datetime(2026, 1, 1, tzinfo=UTC),
                commission=0.0,
            )
        ]
    )

    result = check.check(_order(ORDER_SIDE_BUY, quantity=30), portfolio)

    assert result.passed is False


def test_sell_reducing_position_is_allowed_even_near_limit() -> None:
    check = MaxPositionSizeCheck(max_shares_per_symbol=100)
    portfolio = Portfolio(starting_cash=100_000.0)

    result = check.check(_order(ORDER_SIDE_SELL, quantity=10), portfolio)

    assert result.passed is True
