import pytest
from strategy.core.constants import ORDER_SIDE_BUY, ORDER_SIDE_SELL
from strategy.core.cost_model import (
    AggregateCostModel,
    BpsSlippageModel,
    FlatFeeModel,
    PercentOfNotionalModel,
    PerShareFeeModel,
    groww_delivery_cost_model,
    groww_intraday_cost_model,
    kite_delivery_cost_model,
    kite_intraday_cost_model,
)


def test_per_share_fee_model_scales_with_quantity() -> None:
    model = PerShareFeeModel(cost_per_share=0.5)
    assert model.get_cost(quantity=10, price=100.0) == 5.0


def test_percent_of_notional_model_scales_with_trade_value() -> None:
    model = PercentOfNotionalModel(bps=3.0)  # 0.03%
    assert model.get_cost(quantity=10, price=100.0) == 100.0 * 10 * 3.0 / 10_000


def test_aggregate_cost_model_sums_by_default() -> None:
    model = AggregateCostModel(models=(FlatFeeModel(fee=20.0), PerShareFeeModel(cost_per_share=0.5)))
    assert model.get_cost(quantity=10, price=100.0) == 25.0  # 20 + 10*0.5


def test_aggregate_cost_model_min_picks_cheaper_component() -> None:
    # "0.1% of notional or Rs 20, whichever is lower" is exactly how Kite
    # and Groww cap their brokerage.
    model = AggregateCostModel(
        models=(PercentOfNotionalModel(bps=10.0), FlatFeeModel(fee=20.0)),
        aggregate="min",
    )
    assert model.get_cost(quantity=10, price=100.0) == min(100.0 * 10 * 10.0 / 10_000, 20.0)


def test_aggregate_cost_model_raises_on_unrecognized_aggregate() -> None:
    model = AggregateCostModel(models=(FlatFeeModel(fee=20.0),), aggregate="bogus")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unrecognized aggregate type"):
        model.get_cost(quantity=10, price=100.0)


def test_bps_slippage_model_worsens_buy_and_sell_in_opposite_directions() -> None:
    model = BpsSlippageModel(bps=100.0)  # 1%
    assert model.get_fill_price(price=100.0, side=ORDER_SIDE_BUY) == 101.0
    assert model.get_fill_price(price=100.0, side=ORDER_SIDE_SELL) == 99.0


def test_bps_slippage_model_zero_bps_is_a_no_op() -> None:
    model = BpsSlippageModel(bps=0.0)
    assert model.get_fill_price(price=100.0, side=ORDER_SIDE_BUY) == 100.0


def test_kite_delivery_cost_model_is_brokerage_free_but_not_charge_free() -> None:
    # Zerodha (zerodha.com/charges): delivery brokerage is Rs 0, but STT
    # (0.1%), exchange transaction charge (0.00307%), SEBI charge
    # (0.0001%), stamp duty (0.015%), and GST on the non-STT charges still
    # apply. A 100-share fill at Rs 100 has notional 10,000.
    model = kite_delivery_cost_model()
    cost = model.get_cost(quantity=100, price=100.0)
    assert cost == pytest.approx(11.874, rel=1e-3)


def test_kite_intraday_cost_model_caps_brokerage_at_flat_fee() -> None:
    # Zerodha intraday brokerage is min(0.03% of notional, Rs 20). At a
    # notional of 10,000,000 (1 crore), 0.03% (3000) is far above the Rs 20
    # cap, so brokerage must be exactly 20, not 3000 - the other statutory
    # charges (STT 2.5bps, exchange 0.307bps, SEBI 0.01bps, stamp 0.3bps)
    # scale with the same large notional, so the total is much bigger than
    # the brokerage component alone.
    model = kite_intraday_cost_model()
    cost = model.get_cost(quantity=1000, price=10_000.0)
    capped_brokerage = 20.0
    statutory = 10_000_000.0 * (2.5 + 0.307 + 0.01 + 0.3) / 10_000
    assert cost == pytest.approx(capped_brokerage + statutory, rel=1e-6)


def test_groww_delivery_cost_model_includes_dp_charge() -> None:
    # Groww (groww.in/pricing): delivery brokerage is min(0.1%, Rs 20),
    # plus the same STT/exchange/SEBI/stamp statutory bundle as Kite, plus
    # a flat Rs 16.5 DP charge Kite does not have.
    model = groww_delivery_cost_model()
    kite_equivalent_charges = kite_delivery_cost_model().get_cost(quantity=10, price=100.0)
    groww_cost = model.get_cost(quantity=10, price=100.0)
    assert groww_cost > kite_equivalent_charges  # DP charge + higher brokerage cap


def test_groww_intraday_cost_model_caps_brokerage_at_flat_fee() -> None:
    # Groww intraday brokerage is min(0.1% of notional, Rs 20). At 1 crore
    # notional, 0.1% (10,000) is far above the cap, so brokerage must be
    # exactly 20, not 10,000.
    model = groww_intraday_cost_model()
    cost = model.get_cost(quantity=1000, price=10_000.0)
    capped_brokerage = 20.0
    statutory = 10_000_000.0 * (2.5 + 0.297 + 0.01 + 0.3) / 10_000
    assert cost == pytest.approx(capped_brokerage + statutory, rel=1e-6)
