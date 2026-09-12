from datetime import UTC, datetime
from pathlib import Path

import pytest
from ingest.core.models import Tick
from strategy.core.constants import (
    ORDER_SIDE_BUY,
    ORDER_SIDE_SELL,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_OPEN,
    ORDER_STATUS_RECONCILING,
    ORDER_TYPE_MARKET,
)
from strategy.core.exceptions import OrderNotCancellableError, UnknownOrderError
from strategy.core.models import Order
from strategy.paper.broker import PaperBroker
from strategy.storage.order_store import OrderStore


def _order(side: str = ORDER_SIDE_BUY, order_id: str = "order-1") -> Order:
    return Order(
        symbol="NSE-RELIANCE",
        side=side,
        quantity=10,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
        order_id=order_id,
    )


def _tick(symbol: str = "NSE-RELIANCE", price: float = 110.0) -> Tick:
    return Tick(
        symbol=symbol,
        ts=datetime(2026, 1, 2, tzinfo=UTC),
        price=price,
        volume=100,
        provider="kite",
    )


def _broker() -> PaperBroker:
    return PaperBroker(order_store=OrderStore(db_path=Path(":memory:")))


async def test_submit_order_writes_open_state_and_returns_it() -> None:
    broker = _broker()

    state = await broker.submit_order(_order())

    assert state.status == ORDER_STATUS_OPEN
    assert state.order.order_id == "order-1"


async def test_on_tick_fills_matching_symbol_order() -> None:
    broker = _broker()
    await broker.submit_order(_order())

    fills = await broker.on_tick(_tick(price=110.0))

    assert len(fills) == 1
    assert fills[0].fill_price == 110.0
    assert fills[0].order.order_id == "order-1"


async def test_on_tick_ignores_other_symbols() -> None:
    broker = _broker()
    await broker.submit_order(_order())

    fills = await broker.on_tick(_tick(symbol="NSE-TCS", price=500.0))

    assert fills == []


async def test_fill_removes_order_from_open_orders() -> None:
    broker = _broker()
    await broker.submit_order(_order())
    await broker.on_tick(_tick())

    # A second tick must not fill the same order again.
    second_fills = await broker.on_tick(_tick())
    assert second_fills == []


async def test_get_fills_returns_recorded_fills_for_order() -> None:
    broker = _broker()
    await broker.submit_order(_order())
    await broker.on_tick(_tick(price=110.0))

    fills = await broker.get_fills("order-1")

    assert len(fills) == 1
    assert fills[0].fill_price == 110.0


async def test_get_fills_empty_for_unfilled_order() -> None:
    broker = _broker()
    await broker.submit_order(_order())

    assert await broker.get_fills("order-1") == []


async def test_cancel_order_removes_from_open_and_marks_cancelled() -> None:
    store = OrderStore(db_path=Path(":memory:"))
    broker = PaperBroker(order_store=store)
    await broker.submit_order(_order())

    await broker.cancel_order("order-1")

    state = store.get_state("order-1")
    assert state is not None
    assert state.status == ORDER_STATUS_CANCELLED
    # Cancelled order no longer fills on a later tick.
    assert await broker.on_tick(_tick()) == []


async def test_cancel_unknown_order_raises() -> None:
    broker = _broker()

    with pytest.raises(UnknownOrderError):
        await broker.cancel_order("does-not-exist")


async def test_cancel_already_filled_order_raises() -> None:
    broker = _broker()
    await broker.submit_order(_order())
    await broker.on_tick(_tick())

    with pytest.raises(OrderNotCancellableError):
        await broker.cancel_order("order-1")


async def test_match_pending_orders_not_supported() -> None:
    broker = _broker()

    with pytest.raises(NotImplementedError):
        await broker.match_pending_orders({})


async def test_close_marks_remaining_orders_reconciling_and_returns_them() -> None:
    store = OrderStore(db_path=Path(":memory:"))
    broker = PaperBroker(order_store=store)
    await broker.submit_order(_order())

    remaining = await broker.close()

    assert [o.order_id for o in remaining] == ["order-1"]
    state = store.get_state("order-1")
    assert state is not None
    assert state.status == ORDER_STATUS_RECONCILING
    # Broker no longer considers the order open after close().
    assert await broker.on_tick(_tick()) == []


async def test_resume_from_store_reloads_non_terminal_orders() -> None:
    store = OrderStore(db_path=Path(":memory:"))
    first_broker = PaperBroker(order_store=store)
    await first_broker.submit_order(_order())
    await first_broker.close()  # simulate the process stopping mid-flight

    resumed_broker = PaperBroker(order_store=store)
    await resumed_broker.resume_from_store()

    fills = await resumed_broker.on_tick(_tick(price=115.0))
    assert len(fills) == 1
    assert fills[0].order.order_id == "order-1"


async def test_sell_and_buy_orders_both_fill_independently() -> None:
    broker = _broker()
    await broker.submit_order(_order(side=ORDER_SIDE_BUY, order_id="buy-1"))
    await broker.submit_order(_order(side=ORDER_SIDE_SELL, order_id="sell-1"))

    fills = await broker.on_tick(_tick(price=100.0))

    assert {f.order.order_id for f in fills} == {"buy-1", "sell-1"}
