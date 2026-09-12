from lib.math.cost_models import (
    groww_delivery_cost,
    groww_intraday_cost,
    kite_delivery_cost,
    kite_intraday_cost,
    slippage_fill_price,
)


def test_kite_delivery_cost_is_positive_for_a_real_fill() -> None:
    assert kite_delivery_cost(quantity=10, price=2500.0) > 0.0


def test_kite_intraday_cost_brokerage_is_capped() -> None:
    # A huge notional should hit the Rs 20/order cap, not scale unbounded.
    huge = kite_intraday_cost(quantity=100_000, price=2500.0)
    small = kite_intraday_cost(quantity=1, price=2500.0)
    assert huge > small
    assert huge < 100_000 * 2500.0 * 0.0003 * 2  # sanity: not the uncapped bps rate


def test_groww_costs_are_positive() -> None:
    assert groww_delivery_cost(quantity=5, price=500.0) > 0.0
    assert groww_intraday_cost(quantity=5, price=500.0) > 0.0


def test_slippage_fill_price_buy_pays_more_sell_receives_less() -> None:
    assert slippage_fill_price(100.0, "buy", bps=10.0) > 100.0
    assert slippage_fill_price(100.0, "sell", bps=10.0) < 100.0
    assert slippage_fill_price(100.0, "buy", bps=0.0) == 100.0
