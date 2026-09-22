from dataclasses import replace

import pytest

from openticker.core.risk.aggregate import evaluate_strategy
from openticker.core.risk.models import (
    BreachReason,
    LegState,
    LockMode,
    PositionRisk,
    ProfitLock,
    StrategyLimits,
    StrategyRisk,
    StrategyStopReason,
    TrailingStop,
    TrailMode,
)
from openticker.ports.models import Side

# A short straddle: both legs sold at 100, 50 units each, so every point is 50 rupees.
CE = PositionRisk(
    side=Side.SELL,
    entry_price=100.0,
    quantity=50,
    initial_sl=None,
    current_sl=None,
    target=None,
    highest_price=None,
    lowest_price=None,
    capital_cap=None,
)
LEGS = (LegState("ce", CE, 0.0), LegState("pe", CE, 0.0))


def run(**limits: object) -> StrategyRisk:
    return StrategyRisk(
        limits=StrategyLimits(**limits),  # type: ignore[arg-type]
        peak_mtm=0.0,
        lock_floor=None,
        stops_at_entry=False,
        earlier_runs_realized_pnl=0.0,
    )


def test_mtm_sums_realized_and_open_legs() -> None:
    legs = (LegState("ce", CE, 0.0), LegState("pe", None, -700.0))

    decision = evaluate_strategy(run(), legs, {"ce": 90.0})

    assert decision.evaluated is True
    assert decision.mtm == pytest.approx(500.0 - 700.0)
    assert decision.exit_all is None


def test_combined_stop_loss_exits_all_legs() -> None:
    risk = run(combined_stop_loss=3000.0)

    holding = evaluate_strategy(risk, LEGS, {"ce": 140.0, "pe": 99.0})  # -2000 + 50
    at_limit = evaluate_strategy(risk, LEGS, {"ce": 150.0, "pe": 110.0})  # -2500 - 500

    assert holding.exit_all is None
    assert at_limit.exit_all is StrategyStopReason.COMBINED_STOP_LOSS
    assert at_limit.mtm == pytest.approx(-3000.0)


def test_combined_target_exits_all_legs() -> None:
    decision = evaluate_strategy(run(combined_target=5000.0), LEGS, {"ce": 50.0, "pe": 50.0})

    assert decision.exit_all is StrategyStopReason.COMBINED_TARGET


def test_lock_floor_only_rises() -> None:
    lock = ProfitLock(arm_at=2000.0, lock=1500.0, mode=LockMode.LOCK)
    risk = run(lock_profit=lock)

    below_arm = evaluate_strategy(risk, LEGS, {"ce": 90.0, "pe": 91.0})  # +950
    armed = evaluate_strategy(risk, LEGS, {"ce": 80.0, "pe": 80.0})  # +2000
    risk = replace(risk, peak_mtm=armed.peak_mtm, lock_floor=armed.lock_floor)
    dipped = evaluate_strategy(risk, LEGS, {"ce": 85.0, "pe": 83.0})  # +1600
    breached = evaluate_strategy(risk, LEGS, {"ce": 85.0, "pe": 85.0})  # +1500

    assert below_arm.lock_floor is None
    assert armed.lock_floor == 1500.0
    assert armed.exit_all is None
    assert dipped.lock_floor == 1500.0
    assert dipped.exit_all is None
    assert breached.exit_all is StrategyStopReason.PROFIT_LOCK


def test_lock_arms_from_persisted_peak_after_restart() -> None:
    lock = ProfitLock(arm_at=2000.0, lock=1500.0, mode=LockMode.LOCK)
    restored = replace(run(lock_profit=lock), peak_mtm=2500.0)  # floor not persisted

    decision = evaluate_strategy(restored, LEGS, {"ce": 86.0, "pe": 86.0})  # +1400

    assert decision.exit_all is StrategyStopReason.PROFIT_LOCK


def test_lock_and_trail_raises_floor_by_step() -> None:
    lock = ProfitLock(arm_at=2000.0, lock=1500.0, mode=LockMode.LOCK_AND_TRAIL, trail_step=500.0)
    risk = run(lock_profit=lock)

    floors = []
    for price in (80.0, 77.0, 75.0, 72.0, 70.0):  # +2000, +2300, +2500, +2800, +3000
        decision = evaluate_strategy(risk, LEGS, {"ce": price, "pe": price})
        risk = replace(risk, peak_mtm=decision.peak_mtm, lock_floor=decision.lock_floor)
        floors.append(decision.lock_floor)
    fallen = evaluate_strategy(risk, LEGS, {"ce": 75.0, "pe": 75.0})  # back to +2500

    assert floors == [1500.0, 1500.0, 2000.0, 2000.0, 2500.0]
    assert fallen.lock_floor == 2500.0
    assert fallen.exit_all is StrategyStopReason.PROFIT_LOCK


def test_removed_lock_ignores_persisted_floor() -> None:
    risk = replace(run(), peak_mtm=3000.0, lock_floor=2500.0)

    decision = evaluate_strategy(risk, LEGS, {"ce": 90.0, "pe": 90.0})  # +1000

    assert decision.exit_all is None
    assert decision.lock_floor is None


def test_daily_loss_limit_counts_earlier_runs() -> None:
    first = run(daily_loss_limit=4000.0)
    second = replace(first, earlier_runs_realized_pnl=-3000.0)
    prices = {"ce": 110.0, "pe": 100.0}  # -500 this run

    assert evaluate_strategy(first, LEGS, prices).exit_all is None
    decision = evaluate_strategy(second, LEGS, {"ce": 120.0, "pe": 100.0})  # -1000

    assert decision.exit_all is StrategyStopReason.DAILY_LOSS_LIMIT


def test_per_leg_stop_exits_only_that_leg() -> None:
    stopped = replace(CE, initial_sl=130.0)
    legs = (LegState("ce", stopped, 0.0), LegState("pe", CE, 0.0))

    decision = evaluate_strategy(run(), legs, {"ce": 131.0, "pe": 70.0})

    assert [(exit.leg_id, exit.reason) for exit in decision.leg_exits] == [
        ("ce", BreachReason.STOP_LOSS)
    ]
    assert decision.exit_all is None


def test_leg_stop_moves_other_winning_legs_to_entry() -> None:
    stopped = replace(CE, initial_sl=130.0, current_sl=130.0)
    legs = (LegState("ce", stopped, 0.0), LegState("pe", CE, 0.0))
    risk = run(stops_to_entry_on_leg_stop=True, combined_stop_loss=1000.0)

    decision = evaluate_strategy(risk, legs, {"ce": 131.0, "pe": 70.0})  # -1550 + 1500

    assert decision.stops_moved_to_entry == ("pe",)
    assert decision.legs[1].risk is not None and decision.legs[1].risk.current_sl == 100.0
    assert decision.legs[0].risk is not None and decision.legs[0].risk.current_sl == 130.0
    assert decision.stops_at_entry is True


def test_stops_to_entry_skips_losing_and_looser_legs() -> None:
    losing = CE  # short at 100, now 105: a stop at entry would close it at once
    tighter = replace(CE, current_sl=95.0)  # already better than entry
    stopped = replace(CE, initial_sl=130.0)
    legs = (
        LegState("stopped", stopped, 0.0),
        LegState("losing", losing, 0.0),
        LegState("tighter", tighter, 0.0),
    )
    risk = run(stops_to_entry_on_leg_stop=True)

    decision = evaluate_strategy(risk, legs, {"stopped": 131.0, "losing": 105.0, "tighter": 90.0})

    assert decision.stops_moved_to_entry == ()
    assert decision.stops_at_entry is False
    assert decision.legs[2].risk is not None and decision.legs[2].risk.current_sl == 95.0


def test_stops_at_entry_bypasses_combined_stop_loss_not_target() -> None:
    risk = replace(run(combined_stop_loss=1000.0, combined_target=3000.0), stops_at_entry=True)
    legs = (LegState("ce", None, -1000.0), LegState("pe", CE, 0.0))

    loss = evaluate_strategy(risk, legs, {"pe": 110.0})  # -1000 - 500
    win = evaluate_strategy(risk, legs, {"pe": 0.05})  # -1000 + 4997.50

    assert loss.exit_all is None
    assert win.exit_all is StrategyStopReason.COMBINED_TARGET


def test_target_exit_does_not_move_stops_to_entry() -> None:
    target_hit = replace(CE, target=60.0)
    legs = (LegState("ce", target_hit, 0.0), LegState("pe", CE, 0.0))

    decision = evaluate_strategy(
        run(stops_to_entry_on_leg_stop=True), legs, {"ce": 59.0, "pe": 90.0}
    )

    assert decision.leg_exits[0].reason is BreachReason.TARGET
    assert decision.stops_moved_to_entry == ()


def test_missing_price_skips_strategy_rules_and_keeps_state() -> None:
    risk = replace(run(combined_stop_loss=100.0), peak_mtm=800.0, lock_floor=None)
    stopped = replace(CE, initial_sl=130.0)
    legs = (LegState("ce", stopped, 0.0), LegState("pe", CE, 0.0))

    decision = evaluate_strategy(risk, legs, {"ce": 131.0, "pe": 0.0})

    assert decision.evaluated is False
    assert decision.mtm is None
    assert decision.exit_all is None
    assert decision.peak_mtm == 800.0
    assert [exit.leg_id for exit in decision.leg_exits] == ["ce"]  # priced legs still judged


def test_leg_trailing_state_is_carried() -> None:
    trailing = replace(CE, trailing=TrailingStop(mode=TrailMode.CONTINUOUS, step=10.0, trigger=5.0))
    legs = (LegState("ce", trailing, 0.0),)

    decision = evaluate_strategy(run(), legs, {"ce": 80.0})

    assert decision.legs[0].risk is not None
    assert decision.legs[0].risk.current_sl == 90.0
    assert decision.legs[0].risk.lowest_price == 80.0


def test_daily_loss_checked_before_combined_stop_loss() -> None:
    risk = replace(
        run(combined_stop_loss=1000.0, daily_loss_limit=1000.0), earlier_runs_realized_pnl=-10.0
    )

    decision = evaluate_strategy(risk, LEGS, {"ce": 120.0, "pe": 100.0})  # -1000

    assert decision.exit_all is StrategyStopReason.DAILY_LOSS_LIMIT


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"arm_at": 2000.0, "lock": 2000.0, "mode": LockMode.LOCK}, "below"),
        ({"arm_at": 0.0, "lock": 0.0, "mode": LockMode.LOCK}, "positive profit"),
        ({"arm_at": 2000.0, "lock": -1.0, "mode": LockMode.LOCK}, "zero or more"),
        ({"arm_at": 2000.0, "lock": 0.0, "mode": LockMode.LOCK_AND_TRAIL}, "trail step"),
        (
            {"arm_at": 2000.0, "lock": 0.0, "mode": LockMode.LOCK, "trail_step": 100.0},
            "only applies",
        ),
    ],
)
def test_profit_lock_rejects_bad_configuration(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ProfitLock(**kwargs)  # type: ignore[arg-type]


def test_lock_at_zero_is_allowed() -> None:
    assert ProfitLock(arm_at=1000.0, lock=0.0, mode=LockMode.LOCK).lock == 0.0


@pytest.mark.parametrize("field", ["combined_stop_loss", "combined_target", "daily_loss_limit"])
def test_limits_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        StrategyLimits(**{field: -3000.0})  # type: ignore[arg-type]


def test_floor_never_falls_when_lock_is_edited() -> None:
    lowered = ProfitLock(arm_at=2000.0, lock=1000.0, mode=LockMode.LOCK)
    risk = replace(run(lock_profit=lowered), peak_mtm=3000.0, lock_floor=2500.0)

    decision = evaluate_strategy(risk, LEGS, {"ce": 75.0, "pe": 75.0})  # +2500

    assert decision.lock_floor == 2500.0
    assert decision.exit_all is StrategyStopReason.PROFIT_LOCK


def test_leg_exiting_on_target_in_the_same_tick_is_not_moved_to_entry() -> None:
    stopped = replace(CE, initial_sl=130.0)
    winner = replace(CE, target=60.0)
    legs = (LegState("ce", stopped, 0.0), LegState("pe", winner, 0.0))

    decision = evaluate_strategy(
        run(stops_to_entry_on_leg_stop=True), legs, {"ce": 131.0, "pe": 59.0}
    )

    assert [exit.reason for exit in decision.leg_exits] == [
        BreachReason.STOP_LOSS,
        BreachReason.TARGET,
    ]
    assert decision.stops_moved_to_entry == ()
