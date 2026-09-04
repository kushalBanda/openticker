from datetime import UTC, datetime

from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.action import EnterLongAction, ExitLongAction
from strategy.core.constants import ORDER_SIDE_BUY, ORDER_TYPE_MARKET
from strategy.core.models import Fill, Order
from strategy.core.portfolio import Portfolio


def _bar(close: float) -> Bar:
    return Bar(
        symbol="NSE-RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        provider="test",
    )


def _fill(quantity: float) -> Fill:
    order = Order(
        symbol="NSE-RELIANCE",
        side=ORDER_SIDE_BUY,
        quantity=int(quantity),
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return Fill(order=order, fill_price=100.0, fill_ts=datetime(2026, 1, 1, tzinfo=UTC), commission=0.0)


async def test_enter_long_action_submits_buy_when_flat() -> None:
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    action = EnterLongAction(quantity=10)

    await action.execute("NSE-RELIANCE", _bar(100.0), portfolio, broker)

    fills = await broker.match_pending_orders({"NSE-RELIANCE": _bar(110.0)})
    assert len(fills) == 1
    assert fills[0].order.quantity == 10


async def test_enter_long_action_no_ops_when_already_in_position() -> None:
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    portfolio.apply_fills([_fill(5)])

    action = EnterLongAction(quantity=10)
    await action.execute("NSE-RELIANCE", _bar(100.0), portfolio, broker)

    fills = await broker.match_pending_orders({"NSE-RELIANCE": _bar(110.0)})
    assert fills == []


async def test_exit_long_action_submits_sell_for_full_position() -> None:
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    portfolio.apply_fills([_fill(10)])

    action = ExitLongAction()
    await action.execute("NSE-RELIANCE", _bar(100.0), portfolio, broker)

    fills = await broker.match_pending_orders({"NSE-RELIANCE": _bar(110.0)})
    assert len(fills) == 1
    assert fills[0].order.quantity == 10


async def test_exit_long_action_no_ops_when_flat() -> None:
    broker = BacktestBroker()
    portfolio = Portfolio(starting_cash=100_000.0)
    action = ExitLongAction()

    await action.execute("NSE-RELIANCE", _bar(100.0), portfolio, broker)

    fills = await broker.match_pending_orders({"NSE-RELIANCE": _bar(110.0)})
    assert fills == []
