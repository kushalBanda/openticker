from datetime import UTC, datetime

import pytest

from openticker.core.orders.matching import match_resting
from openticker.core.orders.models import Order, OrderStatus, OrderType
from openticker.ports.models import Product, Side
from tests.fixtures.fake_broker import FAKE_INSTRUMENT


def resting(
    kind: OrderType,
    side: Side,
    price: float | None = None,
    trigger: float | None = None,
    triggered: bool = False,
) -> Order:
    return Order(
        order_id="SB1",
        instrument=FAKE_INSTRUMENT,
        side=side,
        quantity=1,
        product=Product.MIS,
        order_type=kind,
        status=OrderStatus.PENDING,
        fill_price=None,
        reason=None,
        triggered_by="test",
        placed_at=datetime(2026, 9, 22, 4, 0, tzinfo=UTC),
        strategy_id=None,
        run_id=None,
        price=price,
        trigger_price=trigger,
        triggered=triggered,
    )


@pytest.mark.parametrize(
    ("side", "last", "fills"),
    [(Side.BUY, 100.0, True), (Side.BUY, 99.0, True), (Side.BUY, 100.05, False),
     (Side.SELL, 100.0, True), (Side.SELL, 101.0, True), (Side.SELL, 99.95, False)],
)  # fmt: skip
def test_limit_fills_at_or_through_its_price(side: Side, last: float, fills: bool) -> None:
    assert match_resting(resting(OrderType.LIMIT, side, price=100.0), last).fill is fills


@pytest.mark.parametrize(
    ("side", "last", "fills"),
    [(Side.BUY, 100.0, True), (Side.BUY, 99.95, False),
     (Side.SELL, 100.0, True), (Side.SELL, 100.05, False)],
)  # fmt: skip
def test_sl_m_fills_once_the_trigger_is_reached(side: Side, last: float, fills: bool) -> None:
    assert match_resting(resting(OrderType.SL_M, side, trigger=100.0), last).fill is fills


def test_sl_arms_at_the_trigger_then_rests_as_a_limit() -> None:
    stop_buy = resting(OrderType.SL, Side.BUY, price=101.0, trigger=100.0)

    beyond_limit = match_resting(stop_buy, 102.0)  # jumped past both
    not_yet = match_resting(stop_buy, 99.0)

    assert (beyond_limit.triggered, beyond_limit.fill) == (True, False)
    assert (not_yet.triggered, not_yet.fill) == (False, False)
    armed = resting(OrderType.SL, Side.BUY, price=101.0, trigger=100.0, triggered=True)
    assert match_resting(armed, 99.0) == match_resting(armed, 99.0)
    assert match_resting(armed, 99.0).fill  # armed: below the trigger again still fills
    assert match_resting(armed, 99.0).triggered


def test_sl_sell_arms_on_a_fall() -> None:
    stop_sell = resting(OrderType.SL, Side.SELL, price=99.0, trigger=100.0)

    assert match_resting(stop_sell, 99.5).fill
    assert not match_resting(stop_sell, 100.5).triggered
