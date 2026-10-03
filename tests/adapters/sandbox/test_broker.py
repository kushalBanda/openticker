import threading
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker
from openticker.core.orders.models import Order, OrderRequest, OrderStatus, OrderType
from openticker.ports.models import Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker
from tests.fixtures.sandbox import frictionless

NOW = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _order(side: Side, quantity: int, product: Product = Product.CNC) -> OrderRequest:
    return OrderRequest(
        FAKE_INSTRUMENT, side, quantity, product, OrderType.MARKET, None, "test", "s1", "r1"
    )


def _sandbox(market: PricedBroker, capital: float = 100_000.0) -> SandboxBroker:
    return SandboxBroker("fake", market, frictionless(capital))


def _pending(sandbox: SandboxBroker, order_id: str) -> Order:
    order = sandbox.get_order(order_id)
    assert order is not None
    return order


def test_market_order_fills_at_the_live_price_and_blocks_margin() -> None:
    market = PricedBroker(price=1000.0)
    sandbox = _sandbox(market)

    result = sandbox.place_order(_order(Side.BUY, 10))

    assert (result.status, result.fill_price) == (OrderStatus.FILLED, 1000.0)
    funds = sandbox.get_funds()
    assert (funds.used_margin, funds.available_cash) == (10_000.0, 90_000.0)
    [position] = sandbox.get_positions()
    assert (position.quantity, position.average_price) == (10, 1000.0)


def test_selling_back_realizes_pnl_into_available_cash() -> None:
    market = PricedBroker(price=1000.0)
    sandbox = _sandbox(market)
    sandbox.place_order(_order(Side.BUY, 10))

    market.price = 1100.0
    sandbox.place_order(_order(Side.SELL, 10))

    funds = sandbox.get_funds()
    assert (funds.used_margin, funds.realized_pnl, funds.available_cash) == (0.0, 1000.0, 101_000.0)
    [position] = sandbox.get_positions()
    assert (position.quantity, position.realized_pnl, position.unrealized_pnl) == (0, 1000.0, 0.0)


def test_open_position_is_valued_at_the_live_price() -> None:
    market = PricedBroker(price=1000.0)
    sandbox = _sandbox(market)
    sandbox.place_order(_order(Side.SELL, 10, Product.MIS))

    market.price = 990.0

    [position] = sandbox.get_positions()
    assert (position.quantity, position.unrealized_pnl) == (-10, 100.0)


def test_delivery_cannot_be_sold_short() -> None:
    result = _sandbox(PricedBroker()).place_order(_order(Side.SELL, 1))

    assert result.status is OrderStatus.REJECTED
    assert result.reason is not None and "sold short" in result.reason


def test_insufficient_funds_is_rejected_and_recorded() -> None:
    sandbox = _sandbox(PricedBroker(price=1000.0), capital=5_000.0)

    result = sandbox.place_order(_order(Side.BUY, 10))

    assert result.status is OrderStatus.REJECTED
    assert result.reason is not None and "insufficient sandbox funds" in result.reason
    [order] = sandbox.get_orderbook(10)
    assert (order.status, order.strategy_id, order.run_id) == (OrderStatus.REJECTED, "s1", "r1")
    assert sandbox.get_positions() == []


def test_closing_is_never_refused_for_lack_of_funds() -> None:
    market = PricedBroker(price=1000.0)
    sandbox = _sandbox(market, capital=10_000.0)
    sandbox.place_order(_order(Side.BUY, 50, Product.MIS))  # 5x: all 10,000 as margin

    market.price = 1.0  # a loss of 49,950: far more than the account holds
    result = sandbox.place_order(_order(Side.SELL, 50, Product.MIS))

    assert result.status is OrderStatus.FILLED
    assert sandbox.get_funds().available_cash == pytest.approx(-39_950.0)


def test_stale_quote_is_not_filled() -> None:
    market = PricedBroker(price=1047.6)
    market.day_range = (1262.0, 1290.0)

    result = _sandbox(market).place_order(_order(Side.BUY, 1))

    assert result.status is OrderStatus.REJECTED
    assert result.reason is not None and "no fresh price" in result.reason


def test_concurrent_fills_keep_funds_consistent() -> None:
    sandbox = _sandbox(PricedBroker(price=100.0), capital=1_000_000.0)
    errors: list[BaseException] = []

    def buy() -> None:
        try:
            for _ in range(10):
                assert sandbox.place_order(_order(Side.BUY, 1)).status is OrderStatus.FILLED
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=buy) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    [position] = sandbox.get_positions()
    assert position.quantity == 40
    assert sandbox.get_funds().used_margin == pytest.approx(4_000.0)


def _resting(
    side: Side,
    quantity: int,
    kind: OrderType,
    price: float | None = None,
    trigger: float | None = None,
    product: Product = Product.CNC,
) -> OrderRequest:
    return OrderRequest(
        FAKE_INSTRUMENT, side, quantity, product, kind, price, "test", trigger_price=trigger
    )


def test_a_limit_away_from_the_market_rests_and_holds_margin() -> None:
    sandbox = _sandbox(PricedBroker(price=1000.0))

    result = sandbox.place_order(_resting(Side.BUY, 10, OrderType.LIMIT, price=950.0))

    assert result.status is OrderStatus.PENDING
    assert sandbox.get_funds().used_margin == 9_500.0  # valued at the limit
    assert sandbox.get_positions() == []
    [pending] = sandbox.pending_orders()
    assert (pending.order_id, pending.price) == (result.broker_order_id, 950.0)


def test_a_limit_the_market_is_already_through_fills_at_the_better_price() -> None:
    sandbox = _sandbox(PricedBroker(price=1000.0))

    result = sandbox.place_order(_resting(Side.BUY, 10, OrderType.LIMIT, price=1050.0))

    assert (result.status, result.fill_price) == (OrderStatus.FILLED, 1000.0)


def test_a_stop_whose_trigger_is_already_crossed_is_refused() -> None:
    sandbox = _sandbox(PricedBroker(price=1000.0))

    result = sandbox.place_order(
        _resting(Side.SELL, 10, OrderType.SL_M, trigger=1010.0, product=Product.MIS)
    )

    assert result.status is OrderStatus.REJECTED
    assert result.reason is not None and "already crossed" in result.reason
    assert sandbox.get_funds().used_margin == 0.0


def test_a_resting_order_needs_the_funds_for_what_it_would_open() -> None:
    sandbox = _sandbox(PricedBroker(price=1000.0), capital=10_000.0)

    result = sandbox.place_order(_resting(Side.BUY, 11, OrderType.LIMIT, price=950.0))

    assert result.status is OrderStatus.REJECTED
    assert result.reason is not None and "insufficient" in result.reason


def test_a_resting_close_holds_no_margin_and_cnc_cannot_rest_short() -> None:
    sandbox = _sandbox(PricedBroker(price=1000.0))
    sandbox.place_order(_order(Side.BUY, 10))

    closing = sandbox.place_order(_resting(Side.SELL, 10, OrderType.LIMIT, price=1100.0))
    short = sandbox.place_order(_resting(Side.SELL, 11, OrderType.LIMIT, price=1100.0))

    assert closing.status is OrderStatus.PENDING
    assert sandbox.get_funds().used_margin == 10_000.0  # only the open position's
    assert short.status is OrderStatus.REJECTED


def test_filling_a_pending_order_swaps_its_reservation_for_real_margin() -> None:
    sandbox = _sandbox(PricedBroker(price=1000.0))
    placed = sandbox.place_order(_resting(Side.BUY, 10, OrderType.LIMIT, price=950.0))
    assert placed.broker_order_id is not None

    filled = sandbox.fill_pending(_pending(sandbox, placed.broker_order_id), 948.0, NOW)
    again = sandbox.fill_pending(_pending(sandbox, placed.broker_order_id), 940.0, NOW)

    assert (filled.status, filled.fill_price) == (OrderStatus.FILLED, 948.0)
    assert sandbox.get_funds().used_margin == 9_480.0
    [position] = sandbox.get_positions()
    assert (position.quantity, position.average_price) == (10, 948.0)
    assert again.status is OrderStatus.FILLED and again.reason is not None  # untouched
    assert sandbox.pending_orders() == []


def test_a_pending_order_the_funds_no_longer_cover_is_rejected_and_releases_its_hold() -> None:
    market = PricedBroker(price=1000.0)
    sandbox = _sandbox(market, capital=20_000.0)
    placed = sandbox.place_order(_resting(Side.BUY, 10, OrderType.LIMIT, price=950.0))
    sandbox.place_order(_order(Side.BUY, 10))  # uses 10,000 more
    assert placed.broker_order_id is not None

    pending = _pending(sandbox, placed.broker_order_id)
    result = sandbox.fill_pending(pending, 1500.0, NOW)  # gapped far above

    assert result.status is OrderStatus.REJECTED
    assert sandbox.get_funds().used_margin == 10_000.0


def test_cancel_releases_the_hold_and_is_idempotent() -> None:
    sandbox = _sandbox(PricedBroker(price=1000.0))
    placed = sandbox.place_order(_resting(Side.BUY, 10, OrderType.LIMIT, price=950.0))
    assert placed.broker_order_id is not None

    cancelled = sandbox.cancel_order(placed.broker_order_id)
    again = sandbox.cancel_order(placed.broker_order_id)
    unknown = sandbox.cancel_order("SBNOPE")

    assert cancelled.status is OrderStatus.CANCELLED
    assert sandbox.get_funds().used_margin == 0.0
    assert again.status is OrderStatus.CANCELLED and again.reason is not None
    assert again.reason.endswith("nothing to change")
    assert unknown.status is OrderStatus.REJECTED


def test_arming_an_sl_is_remembered() -> None:
    sandbox = _sandbox(PricedBroker(price=1000.0))
    placed = sandbox.place_order(
        _resting(Side.BUY, 1, OrderType.SL, price=1020.0, trigger=1010.0, product=Product.MIS)
    )
    assert placed.broker_order_id is not None

    sandbox.arm_pending(_pending(sandbox, placed.broker_order_id), NOW)

    [pending] = sandbox.pending_orders()
    assert pending.triggered


def test_open_positions_lists_every_non_zero_position_without_prices() -> None:
    sandbox = _sandbox(PricedBroker(price=100.0))
    sandbox.place_order(_order(Side.BUY, 5, Product.MIS))
    sandbox.place_order(_order(Side.SELL, 5, Product.MIS))
    sandbox.place_order(_order(Side.BUY, 5, Product.CNC))

    [position] = sandbox.open_positions()

    assert (position.product, position.quantity, position.last_price) == (Product.CNC, 5, None)


def test_market_depth_comes_from_the_real_broker() -> None:
    market = PricedBroker()

    passed = _sandbox(market).get_market_depth(FAKE_INSTRUMENT)
    direct = market.get_market_depth(FAKE_INSTRUMENT)

    assert replace(passed, as_of=direct.as_of) == direct


def test_preview_margin_matches_what_a_fill_blocks_and_writes_nothing() -> None:
    market = PricedBroker(price=1000.0)
    sandbox = _sandbox(market)
    sandbox.place_order(_order(Side.BUY, 10))

    more = sandbox.preview_margin(FAKE_INSTRUMENT, Side.BUY, 50, Product.CNC, 1000.0)
    out = sandbox.preview_margin(FAKE_INSTRUMENT, Side.SELL, 10, Product.CNC, 1000.0)

    assert (more.required, more.available, more.fits) == (50_000.0, 90_000.0, True)
    assert (out.required, out.released) == (0.0, 10_000.0)
    assert sandbox.get_funds().used_margin == 10_000.0
