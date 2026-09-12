from datetime import UTC, datetime

from strategy.core.constants import ORDER_SIDE_BUY, ORDER_TYPE_MARKET
from strategy.core.models import Order


def _order() -> Order:
    return Order(
        symbol="NSE-RELIANCE",
        side=ORDER_SIDE_BUY,
        quantity=10,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_order_id_defaults_to_a_non_empty_string() -> None:
    order = _order()

    assert isinstance(order.order_id, str)
    assert order.order_id != ""


def test_each_order_gets_a_distinct_order_id() -> None:
    first = _order()
    second = _order()

    assert first.order_id != second.order_id


def test_order_id_can_be_set_explicitly_for_reconciliation() -> None:
    order = Order(
        symbol="NSE-RELIANCE",
        side=ORDER_SIDE_BUY,
        quantity=10,
        order_type=ORDER_TYPE_MARKET,
        placed_at_ts=datetime(2026, 1, 1, tzinfo=UTC),
        order_id="client-order-123",
    )

    assert order.order_id == "client-order-123"
