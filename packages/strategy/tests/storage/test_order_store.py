from datetime import UTC, datetime
from pathlib import Path

from strategy.core.constants import (
    ORDER_SIDE_BUY,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_OPEN,
    ORDER_STATUS_SUBMITTING,
    ORDER_TYPE_MARKET,
)
from strategy.core.models import Order, OrderState
from strategy.storage.order_store import OrderStore


def _order(order_id: str = "order-1") -> Order:
    return Order(
        symbol="NSE-RELIANCE",
        side=ORDER_SIDE_BUY,
        quantity=10,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
        order_id=order_id,
    )


def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    store = OrderStore(db_path=tmp_path / "test.duckdb")
    state = OrderState(order=_order(), status=ORDER_STATUS_SUBMITTING)
    store.write_state(state, updated_ts=datetime(2026, 1, 1, tzinfo=UTC))

    store.ensure_schema()

    assert store.get_state("order-1") is not None


def test_write_then_get_round_trips() -> None:
    store = OrderStore(db_path=Path(":memory:"))
    state = OrderState(order=_order(), status=ORDER_STATUS_SUBMITTING)

    store.write_state(state, updated_ts=datetime(2026, 1, 1, tzinfo=UTC))
    result = store.get_state("order-1")

    assert result is not None
    assert result.status == ORDER_STATUS_SUBMITTING
    assert result.order.symbol == "NSE-RELIANCE"
    assert result.order.order_id == "order-1"
    assert result.broker_order_id is None


def test_get_state_missing_order_returns_none() -> None:
    store = OrderStore(db_path=Path(":memory:"))

    assert store.get_state("does-not-exist") is None


def test_write_state_is_upsert_by_order_id() -> None:
    store = OrderStore(db_path=Path(":memory:"))
    order = _order()

    store.write_state(
        OrderState(order=order, status=ORDER_STATUS_SUBMITTING),
        updated_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.write_state(
        OrderState(order=order, status=ORDER_STATUS_OPEN, broker_order_id="kite-123"),
        updated_ts=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
    )

    result = store.get_state("order-1")
    assert result is not None
    assert result.status == ORDER_STATUS_OPEN
    assert result.broker_order_id == "kite-123"


def test_list_non_terminal_excludes_filled_cancelled_rejected() -> None:
    store = OrderStore(db_path=Path(":memory:"))
    store.write_state(
        OrderState(order=_order("open-1"), status=ORDER_STATUS_OPEN),
        updated_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.write_state(
        OrderState(order=_order("submitting-1"), status=ORDER_STATUS_SUBMITTING),
        updated_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.write_state(
        OrderState(order=_order("filled-1"), status=ORDER_STATUS_FILLED),
        updated_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )

    non_terminal = store.list_non_terminal()

    order_ids = {state.order.order_id for state in non_terminal}
    assert order_ids == {"open-1", "submitting-1"}


def test_list_non_terminal_empty_store() -> None:
    store = OrderStore(db_path=Path(":memory:"))

    assert store.list_non_terminal() == []
