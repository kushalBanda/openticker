import math
from dataclasses import replace

import pytest

from openticker.core.risk.models import BreachReason, PositionRisk, TrailingStop, TrailMode
from openticker.core.risk.position import evaluate_position, validate_position
from openticker.ports.models import Side

LONG = PositionRisk(
    side=Side.BUY,
    entry_price=100.0,
    quantity=10,
    initial_sl=95.0,
    current_sl=95.0,
    target=110.0,
    highest_price=None,
    lowest_price=None,
    capital_cap=None,
)
SHORT = replace(LONG, side=Side.SELL, initial_sl=105.0, current_sl=105.0, target=90.0)


# Defect-seeded: each of these reproduces a real bug class found in existing
# trading platforms' risk engines (ADR 9).


def test_evaluate_position_no_sl_no_implicit_stop() -> None:
    no_stop = replace(LONG, initial_sl=None, current_sl=None)

    decision = evaluate_position(no_stop, 99.0)  # back through entry

    assert decision.breached is False
    assert decision.stop_loss is None


def test_evaluate_position_zero_sl_read_as_absent() -> None:
    zero_stop_short = replace(SHORT, initial_sl=0.0, current_sl=0.0)

    decision = evaluate_position(zero_stop_short, 101.0)  # `ltp >= 0` would fire every tick

    assert decision.breached is False
    assert decision.stop_loss is None


def test_evaluate_position_trail_survives_restart() -> None:
    # Restored after a restart: the peak (120) was persisted, current_sl was not,
    # and the price is back near entry. Arming off the current price (101, one
    # point of profit, under the 5-point trigger) would leave the stop at 95;
    # arming off the peak re-derives the 115 stop the position had earned.
    restored = replace(
        LONG,
        current_sl=None,
        target=None,
        highest_price=120.0,
        trailing=TrailingStop(mode=TrailMode.CONTINUOUS, step=5.0, trigger=5.0),
    )

    decision = evaluate_position(restored, 101.0)

    assert decision.stop_loss == 115.0
    assert decision.reason is BreachReason.STOP_LOSS


def test_evaluate_position_peak_persisted_as_zero_is_reseeded() -> None:
    # On a short, a best price stored as 0 would stay the minimum forever and
    # look like a 100-point favourable move.
    zero_trough = replace(
        SHORT,
        lowest_price=0.0,
        trailing=TrailingStop(mode=TrailMode.CONTINUOUS, step=2.0, trigger=1.0),
    )

    decision = evaluate_position(zero_trough, 99.5)

    assert decision.lowest_price == 99.5
    assert decision.stop_loss == 105.0


def test_evaluate_position_short_side_not_doubled() -> None:
    decision = evaluate_position(SHORT, 106.0)

    assert decision.reason is BreachReason.STOP_LOSS
    assert decision.exit_side is Side.BUY  # covers the short, never sells more
    assert decision.exit_quantity == 10


# Stop loss and target


@pytest.mark.parametrize(
    ("risk", "price", "reason"),
    [
        (LONG, 95.0, BreachReason.STOP_LOSS),
        (LONG, 110.0, BreachReason.TARGET),
        (LONG, 100.0, None),
        (SHORT, 105.0, BreachReason.STOP_LOSS),
        (SHORT, 90.0, BreachReason.TARGET),
        (SHORT, 100.0, None),
    ],
)
def test_stop_and_target_fire_at_their_level_on_each_side(
    risk: PositionRisk, price: float, reason: BreachReason | None
) -> None:
    assert evaluate_position(risk, price).reason is reason


def test_long_exit_sells() -> None:
    assert evaluate_position(LONG, 110.0).exit_side is Side.SELL


def test_stop_wins_when_stop_and_target_are_both_crossed() -> None:
    crossed = replace(LONG, current_sl=105.0, target=103.0)

    assert evaluate_position(crossed, 104.0).reason is BreachReason.STOP_LOSS


def test_current_stop_takes_precedence_over_initial() -> None:
    trailed = replace(LONG, current_sl=98.0)

    assert evaluate_position(trailed, 97.0).reason is BreachReason.STOP_LOSS
    assert evaluate_position(trailed, 99.0).breached is False


# Unusable input


@pytest.mark.parametrize("price", [0.0, -1.0, math.nan, math.inf])
def test_unusable_price_is_not_evaluated_and_carries_state_through(price: float) -> None:
    state = replace(LONG, highest_price=104.0)

    decision = evaluate_position(state, price)

    assert decision.evaluated is False
    assert decision.breached is False
    assert decision.stop_loss == 95.0
    assert decision.highest_price == 104.0


def test_missing_entry_disables_trailing_but_keeps_absolute_levels() -> None:
    no_entry = replace(
        LONG,
        entry_price=0.0,
        trailing=TrailingStop(mode=TrailMode.CONTINUOUS, step=1.0, trigger=0.0),
    )

    decision = evaluate_position(no_entry, 105.0)

    assert decision.stop_loss == 95.0  # not dragged to 104 by a fake "profit"
    assert decision.unrealized_pnl == 0.0
    assert evaluate_position(no_entry, 94.0).reason is BreachReason.STOP_LOSS


def test_quantity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="use `side` for direction"):
        replace(LONG, quantity=-10)


# Trailing stop


def test_continuous_trail_follows_the_peak_and_never_loosens() -> None:
    trailing = replace(
        LONG, trailing=TrailingStop(mode=TrailMode.CONTINUOUS, step=3.0, trigger=2.0)
    )

    up = evaluate_position(trailing, 106.0)
    assert up.stop_loss == 103.0
    assert up.detail == "trailing stop moved from 95.0 to 103.0"

    back = evaluate_position(
        replace(trailing, current_sl=up.stop_loss, highest_price=up.highest_price), 104.0
    )
    assert back.stop_loss == 103.0
    assert back.breached is False


def test_trail_waits_for_the_trigger() -> None:
    trailing = replace(
        LONG, trailing=TrailingStop(mode=TrailMode.CONTINUOUS, step=1.0, trigger=5.0)
    )

    assert evaluate_position(trailing, 104.0).stop_loss == 95.0
    assert evaluate_position(trailing, 105.0).stop_loss == 104.0


def test_short_continuous_trail_moves_down() -> None:
    trailing = replace(
        SHORT, target=None, trailing=TrailingStop(TrailMode.CONTINUOUS, step=2.0, trigger=1.0)
    )

    decision = evaluate_position(trailing, 95.0)

    assert decision.lowest_price == 95.0
    assert decision.stop_loss == 97.0


def test_stepped_trail_moves_from_initial_stop_per_completed_trigger() -> None:
    trailing = replace(
        LONG, target=None, trailing=TrailingStop(TrailMode.STEPPED, step=2.0, trigger=4.0)
    )

    assert evaluate_position(trailing, 103.9).stop_loss == 95.0
    assert evaluate_position(trailing, 104.0).stop_loss == 97.0
    assert evaluate_position(trailing, 109.0).stop_loss == 99.0


def test_trail_never_places_stop_beyond_best_price() -> None:
    # Step larger than trigger: unclamped, one trigger of profit would put the stop at 110.
    aggressive = replace(
        LONG,
        initial_sl=100.0,
        current_sl=100.0,
        target=None,
        trailing=TrailingStop(TrailMode.STEPPED, step=10.0, trigger=1.0),
    )

    decision = evaluate_position(aggressive, 101.0)

    assert decision.stop_loss == 101.0


def test_stepped_trail_needs_a_trigger() -> None:
    with pytest.raises(ValueError, match="positive trigger"):
        TrailingStop(TrailMode.STEPPED, step=1.0, trigger=0.0)


# Capital cap and P&L


def test_capital_cap_breaches_when_position_value_exceeds_it() -> None:
    capped = replace(LONG, target=None, capital_cap=1050.0)

    assert evaluate_position(capped, 105.0).breached is False
    decision = evaluate_position(capped, 106.0)
    assert decision.reason is BreachReason.CAPITAL_CAP
    assert decision.exit_side is Side.SELL


def test_unrealized_pnl_on_each_side() -> None:
    assert evaluate_position(LONG, 102.0).unrealized_pnl == 20.0
    assert evaluate_position(SHORT, 102.0).unrealized_pnl == -20.0


# Validation


def test_validate_flags_levels_on_the_wrong_side() -> None:
    wrong = replace(LONG, current_sl=101.0, target=99.0)

    problems = validate_position(wrong)

    assert len(problems) == 2
    assert "stop loss 101.0" in problems[0]
    assert "target 99.0" in problems[1]


def test_validate_uses_reference_price_when_given() -> None:
    assert validate_position(LONG, reference_price=94.0) != []
    assert validate_position(LONG, reference_price=100.0) == []


def test_validate_flags_stepped_trail_problems() -> None:
    risky = replace(
        LONG,
        initial_sl=None,
        current_sl=None,
        trailing=TrailingStop(TrailMode.STEPPED, step=3.0, trigger=2.0),
    )

    problems = validate_position(risky)

    assert any("initial stop loss" in problem for problem in problems)
    assert any("larger than its trigger" in problem for problem in problems)
