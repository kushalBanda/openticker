from dataclasses import replace

import pytest

from openticker.core.risk.models import TrailMode
from openticker.core.strategies.models import Horizon, LegSpec, RelativeExpiry, RiskValue
from openticker.core.strategies.runs import LegStatus, RunLeg, leg_risk, product_for
from openticker.ports.models import Exchange, InstrumentType, Product, Side

SOLD = LegSpec(
    Side.SELL,
    1,
    InstrumentType.CE,
    RelativeExpiry.WEEKLY,
    stop_loss=RiskValue(30.0, percent=True),
    target=RiskValue(20.0, percent=False),
    trailing=RiskValue(10.0, percent=True),
)


def test_a_sold_legs_stop_is_above_its_fill_and_target_below() -> None:
    risk = leg_risk(SOLD, SOLD.side, 200.0, 65)

    assert (risk.initial_sl, risk.current_sl, risk.target) == (260.0, 260.0, 180.0)
    assert risk.trailing is not None
    assert (risk.trailing.mode, risk.trailing.step, risk.trailing.trigger) == (
        TrailMode.CONTINUOUS,
        20.0,
        0.0,
    )
    assert (risk.side, risk.quantity, risk.entry_price) == (Side.SELL, 65, 200.0)


def test_a_bought_legs_stop_is_below_its_fill_and_target_above() -> None:
    bought = replace(SOLD, side=Side.BUY, stop_loss=RiskValue(15.0, percent=False))

    risk = leg_risk(bought, bought.side, 200.0, 65)

    assert (risk.initial_sl, risk.target) == (185.0, 220.0)


def test_a_stop_that_would_sit_below_zero_is_left_unset() -> None:
    bought = replace(SOLD, side=Side.BUY, stop_loss=RiskValue(50.0, percent=False), target=None)

    assert leg_risk(bought, bought.side, 40.0, 65).initial_sl is None


def test_unset_rules_stay_unset() -> None:
    plain = LegSpec(Side.SELL, 1, InstrumentType.PE, RelativeExpiry.WEEKLY)

    risk = leg_risk(plain, plain.side, 100.0, 65)

    assert (risk.initial_sl, risk.target, risk.trailing) == (None, None, None)


def test_horizon_picks_the_product() -> None:
    assert product_for(Horizon.INTRADAY) is Product.MIS
    assert product_for(Horizon.POSITIONAL) is Product.NRML


@pytest.mark.parametrize(
    ("status", "exit_price", "expected"),
    [(LegStatus.CLOSED, 80.0, 1300.0), (LegStatus.OPEN, None, 0.0), (LegStatus.CLOSED, None, 0.0)],
)
def test_a_legs_realized_pnl_counts_only_once_closed(
    status: LegStatus, exit_price: float | None, expected: float
) -> None:
    leg = RunLeg(
        "leg1", "X", Exchange.NFO, Side.SELL, 65, status, entry_price=100.0, exit_price=exit_price
    )

    assert leg.realized_pnl == expected
