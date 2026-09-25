from datetime import UTC, datetime

import pytest

from openticker.core.orders.fills import FillSettings
from openticker.core.orders.matching import Match, match_resting
from openticker.core.orders.models import Order, OrderStatus, OrderType
from openticker.ports.models import Product, Side
from tests.fixtures.fake_broker import FAKE_INSTRUMENT

ONE_TICK = FillSettings(slippage_ticks=1)


def match(order: Order, last: float) -> Match:
    return match_resting(order, last, ONE_TICK)


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
    [(Side.BUY, 99.95, True), (Side.BUY, 100.0, False), (Side.BUY, 100.05, False),
     (Side.SELL, 100.05, True), (Side.SELL, 100.0, False), (Side.SELL, 99.95, False)],
)  # fmt: skip
def test_limit_fills_only_when_traded_through(side: Side, last: float, fills: bool) -> None:
    assert match(resting(OrderType.LIMIT, side, price=100.0), last).fill is fills


def test_limit_fills_at_its_own_price_not_the_better_one() -> None:
    assert match(resting(OrderType.LIMIT, Side.BUY, price=100.0), 98.0).price == 100.0
    assert match(resting(OrderType.LIMIT, Side.SELL, price=100.0), 102.0).price == 100.0


@pytest.mark.parametrize(
    ("side", "last", "fills"),
    [(Side.BUY, 100.0, True), (Side.BUY, 99.95, False),
     (Side.SELL, 100.0, True), (Side.SELL, 100.05, False)],
)  # fmt: skip
def test_sl_m_fills_once_the_trigger_is_reached(side: Side, last: float, fills: bool) -> None:
    assert match(resting(OrderType.SL_M, side, trigger=100.0), last).fill is fills


def test_sl_m_fills_a_tick_against_it_since_a_streamed_price_has_no_book() -> None:
    assert match(resting(OrderType.SL_M, Side.BUY, trigger=100.0), 100.5).price == 100.55
    assert match(resting(OrderType.SL_M, Side.SELL, trigger=100.0), 99.5).price == 99.45


def test_sl_arms_at_the_trigger_then_rests_as_a_limit() -> None:
    stop_buy = resting(OrderType.SL, Side.BUY, price=101.0, trigger=100.0)

    beyond_limit = match(stop_buy, 102.0)  # jumped past both
    not_yet = match(stop_buy, 99.0)

    assert (beyond_limit.triggered, beyond_limit.fill) == (True, False)
    assert (not_yet.triggered, not_yet.fill) == (False, False)
    armed = resting(OrderType.SL, Side.BUY, price=101.0, trigger=100.0, triggered=True)
    assert match(armed, 99.0).fill  # armed: below the trigger again still fills
    assert match(armed, 99.0).triggered
    assert match(armed, 99.0).price == 101.0


def test_sl_sell_arms_on_a_fall() -> None:
    stop_sell = resting(OrderType.SL, Side.SELL, price=99.0, trigger=100.0)

    assert match(stop_sell, 99.5).fill
    assert not match(stop_sell, 100.5).triggered
