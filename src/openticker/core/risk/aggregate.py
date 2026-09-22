"""evaluate_strategy: risk rules over a whole strategy's legs. Pure: no I/O, no
clock, no logging. Rules and their reasons: ADR 19 in docs/adr."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace

from openticker.core.risk.models import (
    BreachReason,
    LegExit,
    LegState,
    LockMode,
    ProfitLock,
    StrategyDecision,
    StrategyRisk,
    StrategyStopReason,
    as_price,
)
from openticker.core.risk.position import evaluate_position
from openticker.ports.models import Side


def evaluate_strategy(
    risk: StrategyRisk, legs: Sequence[LegState], prices: Mapping[str, float]
) -> StrategyDecision:
    """Judge a run at one set of prices, keyed by `leg_id`: each open leg's own
    rules first, then stops to entry, then the P&L-wide rules in the order
    daily loss limit, profit lock, combined stop loss, combined target. The
    P&L-wide rules need every open leg priced; a missing price is never
    guessed, so they are skipped until it arrives."""
    limits = risk.limits
    updated: list[LegState] = []
    exits: list[LegExit] = []
    unpriced: list[str] = []
    mtm = 0.0
    for leg in legs:
        mtm += leg.realized_pnl
        if leg.risk is None:
            updated.append(leg)
            continue
        price = prices.get(leg.leg_id)
        decision = evaluate_position(leg.risk, price) if price is not None else None
        if decision is None or not decision.evaluated:
            unpriced.append(leg.leg_id)
            updated.append(leg)
            continue
        mtm += decision.unrealized_pnl
        updated.append(
            replace(
                leg,
                risk=replace(
                    leg.risk,
                    current_sl=decision.stop_loss,
                    highest_price=decision.highest_price,
                    lowest_price=decision.lowest_price,
                ),
            )
        )
        if decision.reason is not None:
            exits.append(LegExit(leg.leg_id, decision.reason, decision.detail or ""))

    moved: tuple[str, ...] = ()
    stops_at_entry = risk.stops_at_entry
    if limits.stops_to_entry_on_leg_stop and any(
        exit.reason is BreachReason.STOP_LOSS for exit in exits
    ):
        updated, moved = _stops_to_entry(updated, {exit.leg_id for exit in exits}, prices)
        stops_at_entry = stops_at_entry or bool(moved)

    def decide(
        mtm: float | None,
        peak: float,
        floor: float | None,
        reason: StrategyStopReason | None = None,
        detail: str | None = None,
    ) -> StrategyDecision:
        return StrategyDecision(
            evaluated=mtm is not None,
            mtm=mtm,
            exit_all=reason,
            detail=detail,
            leg_exits=tuple(exits),
            stops_moved_to_entry=moved,
            legs=tuple(updated),
            peak_mtm=peak,
            lock_floor=floor,
            stops_at_entry=stops_at_entry,
        )

    if unpriced:
        return decide(
            None,
            risk.peak_mtm,
            risk.lock_floor,
            detail=f"strategy rules not evaluated: no usable price for {', '.join(unpriced)}",
        )

    peak = max(risk.peak_mtm, mtm)
    # A floor left over from a lock the user has since removed must not close anything.
    floor = _lock_floor(limits.lock_profit, peak, risk.lock_floor) if limits.lock_profit else None

    if limits.daily_loss_limit is not None:
        day = risk.earlier_runs_realized_pnl + mtm
        if day <= -limits.daily_loss_limit:
            return decide(
                mtm,
                peak,
                floor,
                StrategyStopReason.DAILY_LOSS_LIMIT,
                f"today's P&L {_rupees(day)} reached the daily loss limit "
                f"{_rupees(-limits.daily_loss_limit)}",
            )
    if floor is not None and mtm <= floor:
        return decide(
            mtm,
            peak,
            floor,
            StrategyStopReason.PROFIT_LOCK,
            f"P&L {_rupees(mtm)} fell to the locked profit {_rupees(floor)}",
        )
    if (
        limits.combined_stop_loss is not None
        and not stops_at_entry
        and mtm <= -limits.combined_stop_loss
    ):
        return decide(
            mtm,
            peak,
            floor,
            StrategyStopReason.COMBINED_STOP_LOSS,
            f"P&L {_rupees(mtm)} reached the combined stop loss "
            f"{_rupees(-limits.combined_stop_loss)}",
        )
    if limits.combined_target is not None and mtm >= limits.combined_target:
        return decide(
            mtm,
            peak,
            floor,
            StrategyStopReason.COMBINED_TARGET,
            f"P&L {_rupees(mtm)} reached the combined target {_rupees(limits.combined_target)}",
        )
    return decide(mtm, peak, floor)


def _lock_floor(lock: ProfitLock, peak: float, floor: float | None) -> float | None:
    if floor is None and peak < lock.arm_at:
        return None
    candidate = lock.lock
    if lock.mode is LockMode.LOCK_AND_TRAIL and lock.trail_step is not None:
        # The tolerance keeps a peak exactly on a step boundary from rounding down a step.
        steps = math.floor((peak - lock.arm_at) / lock.trail_step + 1e-9)
        candidate += steps * lock.trail_step
    return candidate if floor is None else max(floor, candidate)


def _stops_to_entry(
    legs: list[LegState], exiting: set[str], prices: Mapping[str, float]
) -> tuple[list[LegState], tuple[str, ...]]:
    """Move each other open leg's stop to its entry, where that tightens it.
    A leg whose entry is already through the market is left alone: a stop
    there would close it at once, at a loss."""
    result: list[LegState] = []
    moved: list[str] = []
    for leg in legs:
        position = leg.risk
        entry = as_price(position.entry_price) if position is not None else None
        if position is None or entry is None or leg.leg_id in exiting:
            result.append(leg)
            continue
        long = position.side is Side.BUY
        stop = as_price(position.current_sl) or as_price(position.initial_sl)
        price = as_price(prices.get(leg.leg_id))
        if (stop is not None and (stop >= entry if long else stop <= entry)) or (
            price is not None and (entry >= price if long else entry <= price)
        ):
            result.append(leg)
            continue
        result.append(replace(leg, risk=replace(position, current_sl=entry)))
        moved.append(leg.leg_id)
    return result, tuple(moved)


def _rupees(amount: float) -> str:
    return f"{amount:,.2f}"
