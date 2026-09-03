import logging
from datetime import UTC, datetime

import pytest
from ingest.core.models import Bar
from strategy.backtest.broker import BacktestBroker
from strategy.core.constants import (
    ORDER_SIDE_BUY,
    ORDER_SIDE_SELL,
    ORDER_TYPE_MARKET,
)
from strategy.core.engine import BacktestEngine
from strategy.core.interfaces import Broker
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio


def _bar(open_: float) -> Bar:
    return Bar(
        symbol="NSE-RELIANCE",
        interval="1d",
        ts=datetime(2026, 1, 2, tzinfo=UTC),
        open=open_,
        high=open_,
        low=open_,
        close=open_,
        volume=1000,
        provider="test",
    )


def _order(side: str) -> Order:
    return Order(
        symbol="NSE-RELIANCE",
        side=side,
        quantity=10,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def test_submit_then_match_next_bar_fills_at_next_open() -> None:
    broker = BacktestBroker()
    await broker.submit_order(_order(ORDER_SIDE_BUY))

    fills = await broker.match_pending_orders({"NSE-RELIANCE": _bar(open_=110.0)})

    assert len(fills) == 1
    assert fills[0].fill_price == 110.0
    assert fills[0].fill_ts == datetime(2026, 1, 2, tzinfo=UTC)


async def test_slippage_worsens_buy_and_sell_in_opposite_directions() -> None:
    broker = BacktestBroker(slippage_bps=100.0)  # 1%

    await broker.submit_order(_order(ORDER_SIDE_BUY))
    buy_fill = (await broker.match_pending_orders({"NSE-RELIANCE": _bar(open_=100.0)}))[0]
    assert buy_fill.fill_price == 101.0  # buy pays more

    await broker.submit_order(_order(ORDER_SIDE_SELL))
    sell_fill = (await broker.match_pending_orders({"NSE-RELIANCE": _bar(open_=100.0)}))[0]
    assert sell_fill.fill_price == 99.0  # sell receives less


async def test_commission_applied_per_share() -> None:
    broker = BacktestBroker(commission_per_share=0.5)
    await broker.submit_order(_order(ORDER_SIDE_BUY))

    fill = (await broker.match_pending_orders({"NSE-RELIANCE": _bar(open_=100.0)}))[0]

    assert fill.commission == 5.0  # 10 shares * 0.5


async def test_pending_order_held_when_symbol_absent_next_step() -> None:
    broker = BacktestBroker()
    await broker.submit_order(_order(ORDER_SIDE_BUY))

    fills_when_absent = await broker.match_pending_orders({"NSE-TCS": _bar(open_=100.0)})
    assert fills_when_absent == []

    fills_when_present = await broker.match_pending_orders({"NSE-RELIANCE": _bar(open_=110.0)})
    assert len(fills_when_present) == 1
    assert fills_when_present[0].fill_price == 110.0


async def test_no_next_bar_drops_pending_order_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bars = {"NSE-RELIANCE": [_bar(open_=100.0)]}

    class BuyStrategy:
        async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker) -> None:
            await broker.submit_order(_order(ORDER_SIDE_BUY))

    broker = BacktestBroker()
    engine = BacktestEngine(broker, Portfolio(starting_cash=1000.0))

    with caplog.at_level(logging.WARNING, logger="strategy.core.engine"):
        result = await engine.run(bars, BuyStrategy())

    assert result.positions.get("NSE-RELIANCE", 0) == 0
    assert "dropped" in caplog.text
