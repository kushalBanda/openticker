from datetime import UTC, datetime

import pytest
from execution.brokers.paper.broker import PaperBroker
from execution.core.exceptions import InvalidTransitionError
from execution.core.risk_pipeline import RiskPipeline
from execution.risk_checks.max_position_size import MaxPositionSizeCheck
from strategy.core.constants import (
    ORDER_SIDE_BUY,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_REJECTED,
    ORDER_TYPE_MARKET,
)
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


async def test_submit_order_passing_risk_pipeline_fills_at_latest_quote() -> None:
    pipeline = RiskPipeline([MaxPositionSizeCheck(max_shares_per_symbol=1000)])
    portfolio = Portfolio(starting_cash=100_000.0)
    broker = PaperBroker(risk_pipeline=pipeline, portfolio=portfolio)
    broker.update_quote("NSE-RELIANCE", 100.0)

    state = await broker.submit_order(_order(quantity=10))

    assert state.status == ORDER_STATUS_FILLED
    assert portfolio.positions.get("NSE-RELIANCE", 0) == 10
    assert portfolio.cash == 100_000.0 - 1000.0


async def test_submit_order_rejected_by_risk_pipeline_never_fills() -> None:
    pipeline = RiskPipeline([MaxPositionSizeCheck(max_shares_per_symbol=5)])
    portfolio = Portfolio(starting_cash=100_000.0)
    broker = PaperBroker(risk_pipeline=pipeline, portfolio=portfolio)
    broker.update_quote("NSE-RELIANCE", 100.0)

    state = await broker.submit_order(_order(quantity=10))

    assert state.status == ORDER_STATUS_REJECTED
    assert portfolio.positions.get("NSE-RELIANCE", 0) == 0
    assert portfolio.cash == 100_000.0


async def test_submit_order_with_no_known_quote_raises() -> None:
    pipeline = RiskPipeline([])
    portfolio = Portfolio(starting_cash=100_000.0)
    broker = PaperBroker(risk_pipeline=pipeline, portfolio=portfolio)

    with pytest.raises(ValueError, match="no quote known"):
        await broker.submit_order(_order())


async def test_get_fills_returns_fills_for_a_given_order_id() -> None:
    pipeline = RiskPipeline([])
    portfolio = Portfolio(starting_cash=100_000.0)
    broker = PaperBroker(risk_pipeline=pipeline, portfolio=portfolio)
    broker.update_quote("NSE-RELIANCE", 100.0)
    order = _order(quantity=10)

    await broker.submit_order(order)
    order_id = f"{order.symbol}|{order.side}|{order.quantity}|{order.placed_at_ts.isoformat()}"
    fills = await broker.get_fills(order_id)

    assert len(fills) == 1
    assert fills[0].fill_price == 100.0


async def test_close_returns_no_dropped_orders_when_nothing_left_open() -> None:
    pipeline = RiskPipeline([])
    portfolio = Portfolio(starting_cash=100_000.0)
    broker = PaperBroker(risk_pipeline=pipeline, portfolio=portfolio)
    broker.update_quote("NSE-RELIANCE", 100.0)
    await broker.submit_order(_order())

    dropped = await broker.close()

    assert dropped == []


async def test_cancel_order_on_unknown_order_id_raises() -> None:
    pipeline = RiskPipeline([])
    portfolio = Portfolio(starting_cash=100_000.0)
    broker = PaperBroker(risk_pipeline=pipeline, portfolio=portfolio)

    with pytest.raises(KeyError):
        await broker.cancel_order("does-not-exist")


async def test_cancel_order_on_already_filled_order_raises_invalid_transition() -> None:
    pipeline = RiskPipeline([])
    portfolio = Portfolio(starting_cash=100_000.0)
    broker = PaperBroker(risk_pipeline=pipeline, portfolio=portfolio)
    broker.update_quote("NSE-RELIANCE", 100.0)
    order = _order()
    await broker.submit_order(order)
    order_id = f"{order.symbol}|{order.side}|{order.quantity}|{order.placed_at_ts.isoformat()}"

    with pytest.raises(InvalidTransitionError):
        await broker.cancel_order(order_id)
