from datetime import time

import pytest

from openticker.core.strategies.models import (
    Horizon,
    InvalidStrategyError,
    LegSpec,
    OptionsStrategySpec,
    RelativeExpiry,
    RiskValue,
    Schedule,
    StrikeSelector,
    leg_id,
)
from openticker.ports.models import Exchange, InstrumentType, Side

CALL = LegSpec(Side.SELL, 1, InstrumentType.CE, RelativeExpiry.WEEKLY)


def spec(**overrides: object) -> OptionsStrategySpec:
    fields: dict[str, object] = {
        "underlying": "NIFTY 50",
        "exchange": Exchange.NSE,
        "legs": (CALL,),
        "horizon": Horizon.INTRADAY,
    }
    fields.update(overrides)
    return OptionsStrategySpec(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: spec(legs=()), "1 to 10 legs"),
        (lambda: spec(legs=(CALL,) * 11), "1 to 10 legs"),
        (lambda: spec(exchange=Exchange.NFO), "NSE or BSE"),
        (lambda: LegSpec(Side.BUY, 0, InstrumentType.CE, RelativeExpiry.WEEKLY), "lots"),
        (lambda: LegSpec(Side.BUY, 51, InstrumentType.CE, RelativeExpiry.WEEKLY), "lots"),
        (lambda: LegSpec(Side.BUY, 1, InstrumentType.EQ, RelativeExpiry.WEEKLY), "CE, PE or FUT"),
        (lambda: LegSpec(Side.BUY, 1, InstrumentType.FUT, RelativeExpiry.WEEKLY), "monthly"),
        (
            lambda: LegSpec(
                Side.BUY, 1, InstrumentType.FUT, RelativeExpiry.MONTHLY, StrikeSelector()
            ),
            "no strike",
        ),
        (
            lambda: LegSpec(
                Side.SELL,
                1,
                InstrumentType.CE,
                RelativeExpiry.WEEKLY,
                target=RiskValue(100.0, percent=True),
            ),
            "below 100",
        ),
        (lambda: StrikeSelector(offset=21), "within 20"),
        (lambda: StrikeSelector(offset=1, fixed_strike=25000.0), "either"),
        (lambda: RiskValue(0.0, percent=False), "positive"),
        (lambda: Schedule(weekdays=frozenset({5})), "weekdays"),
        (lambda: Schedule(weekdays=frozenset()), "weekdays"),
        (lambda: Schedule(entry_time=time(9, 0)), "outside the session"),
        (lambda: Schedule(exit_time=time(15, 30)), "outside the session"),
        (lambda: Schedule(entry_time=time(10, 0), exit_time=time(10, 0)), "after entry_time"),
        (lambda: spec(schedule=Schedule(exit_time=time(15, 20))), "squared off at 15:15"),
    ],
)
def test_invalid_definitions_say_why(build: object, message: str) -> None:
    with pytest.raises(InvalidStrategyError, match=message):
        build()  # type: ignore[operator]


def test_positional_may_exit_after_intraday_cutoff() -> None:
    late = spec(horizon=Horizon.POSITIONAL, schedule=Schedule(exit_time=time(15, 25)))

    assert late.schedule.exit_time == time(15, 25)


def test_intraday_may_exit_at_the_cutoff() -> None:
    assert spec(schedule=Schedule(exit_time=time(15, 15))).schedule.exit_time == time(15, 15)


def test_legs_are_named_by_position() -> None:
    assert [leg_id(index) for index in range(3)] == ["leg1", "leg2", "leg3"]


def test_a_bought_legs_percent_stop_must_be_below_100() -> None:
    with pytest.raises(InvalidStrategyError, match="bought leg's stop loss"):
        LegSpec(
            Side.BUY,
            1,
            InstrumentType.CE,
            RelativeExpiry.WEEKLY,
            stop_loss=RiskValue(100.0, percent=True),
        )
    LegSpec(
        Side.SELL, 1, InstrumentType.CE, RelativeExpiry.WEEKLY, stop_loss=RiskValue(100.0, True)
    )
