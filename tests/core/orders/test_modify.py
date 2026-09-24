from dataclasses import replace
from datetime import UTC, datetime

import pytest

from openticker.core.orders.models import Order, OrderChanges, OrderStatus, OrderType
from openticker.core.orders.modify import ChangeRefused, apply_changes, describe_change
from openticker.ports.models import Product, Side
from tests.fixtures.fake_broker import FAKE_INSTRUMENT

RESTING = Order(
    order_id="SB1",
    instrument=FAKE_INSTRUMENT,
    side=Side.SELL,
    quantity=10,
    product=Product.MIS,
    order_type=OrderType.SL,
    status=OrderStatus.PENDING,
    fill_price=None,
    reason=None,
    triggered_by="strategy:s1",
    placed_at=datetime(2026, 9, 22, 5, 0, tzinfo=UTC),
    strategy_id="s1",
    run_id="r1",
    price=990.0,
    trigger_price=995.0,
)


def test_a_change_keeps_type_instrument_side_product_and_tags() -> None:
    request = apply_changes(RESTING, OrderChanges(price=985.0))

    assert (request.price, request.trigger_price, request.quantity) == (985.0, 995.0, 10)
    assert (request.instrument, request.side, request.product, request.order_type) == (
        FAKE_INSTRUMENT,
        Side.SELL,
        Product.MIS,
        OrderType.SL,
    )
    assert (request.triggered_by, request.strategy_id, request.run_id) == (
        "strategy:s1",
        "s1",
        "r1",
    )


def test_a_price_on_sl_m_and_a_trigger_on_limit_are_refused() -> None:
    sl_m = replace(RESTING, order_type=OrderType.SL_M, price=None)
    limit = replace(RESTING, order_type=OrderType.LIMIT, trigger_price=None)

    with pytest.raises(ChangeRefused, match="SL-M orders take no price"):
        apply_changes(sl_m, OrderChanges(price=990.0))
    with pytest.raises(ChangeRefused, match="LIMIT orders take no trigger_price"):
        apply_changes(limit, OrderChanges(trigger_price=990.0))


def test_an_order_no_longer_pending_is_refused() -> None:
    filled = replace(RESTING, status=OrderStatus.FILLED)

    with pytest.raises(ChangeRefused, match="is FILLED; only PENDING can change"):
        apply_changes(filled, OrderChanges(quantity=20))


def test_a_change_that_changes_nothing_is_refused() -> None:
    with pytest.raises(ChangeRefused, match="nothing to change"):
        apply_changes(RESTING, OrderChanges())
    with pytest.raises(ChangeRefused, match="nothing to change"):
        apply_changes(RESTING, OrderChanges(quantity=10, price=990.0))


def test_the_description_names_only_what_changed() -> None:
    request = apply_changes(RESTING, OrderChanges(quantity=20, price=990.0, trigger_price=996.0))

    assert describe_change(RESTING, request) == "quantity 10 -> 20, trigger_price 995.0 -> 996.0"
