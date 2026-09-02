from datetime import UTC, datetime

from execution.risk_checks.max_daily_loss import MaxDailyLossCheck
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


def test_kill_switch_rejects_all_orders_once_tripped() -> None:
    check = MaxDailyLossCheck(max_daily_loss_pct=0.05, starting_equity=100_000.0)
    portfolio = Portfolio(starting_cash=93_000.0)  # 7% down from day start

    result = check.check(_order(), portfolio, reference_price=100.0)

    assert result.passed is False

    # Once tripped, stays tripped even if equity recovers within the check's
    # lifetime, until reset_for_new_trading_day is called.
    portfolio_recovered = Portfolio(starting_cash=100_000.0)
    result_after_recovery = check.check(_order(), portfolio_recovered, reference_price=100.0)
    assert result_after_recovery.passed is False


def test_passes_when_loss_within_limit() -> None:
    check = MaxDailyLossCheck(max_daily_loss_pct=0.05, starting_equity=100_000.0)
    portfolio = Portfolio(starting_cash=98_000.0)  # 2% down

    result = check.check(_order(), portfolio, reference_price=100.0)

    assert result.passed is True


def test_resets_at_start_of_new_nse_trading_day() -> None:
    check = MaxDailyLossCheck(max_daily_loss_pct=0.05, starting_equity=100_000.0)
    portfolio = Portfolio(starting_cash=93_000.0)
    check.check(_order(), portfolio, reference_price=100.0)  # trips it

    check.reset_for_new_trading_day(starting_equity=93_000.0)

    fresh_day_portfolio = Portfolio(starting_cash=93_000.0)
    result = check.check(_order(), fresh_day_portfolio, reference_price=100.0)

    assert result.passed is True
