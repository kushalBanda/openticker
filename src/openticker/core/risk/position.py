"""evaluate_position and validate_position: per-position risk rules. Pure: no
I/O, no clock, no logging. Rules and their reasons: ADR 9 in docs/adr."""

import math

from openticker.core.risk.models import (
    BreachReason,
    PositionRisk,
    RiskDecision,
    TrailingStop,
    TrailMode,
    as_price,
)
from openticker.ports.models import Side


def evaluate_position(risk: PositionRisk, last_price: float) -> RiskDecision:
    """Judge one position at one price: update the best price seen, trail the
    stop, then test stop loss, target and capital cap, in that order."""
    long = risk.side is Side.BUY
    entry = as_price(risk.entry_price)
    stop = as_price(risk.current_sl) or as_price(risk.initial_sl)
    target = as_price(risk.target)
    highest = as_price(risk.highest_price)
    lowest = as_price(risk.lowest_price)

    ltp = as_price(last_price)
    if ltp is None:
        return RiskDecision(
            evaluated=False,
            breached=False,
            reason=None,
            detail=f"not evaluated: {last_price} is not a usable price",
            stop_loss=stop,
            highest_price=highest,
            lowest_price=lowest,
            unrealized_pnl=0.0,
            exit_side=None,
            exit_quantity=0,
        )

    seed = entry if entry is not None else ltp
    if long:
        highest = best = max(highest if highest is not None else seed, ltp)
    else:
        lowest = best = min(lowest if lowest is not None else seed, ltp)

    previous_stop = stop
    if risk.trailing is not None and entry is not None:
        favourable = best - entry if long else entry - best
        if favourable > 0 and favourable >= risk.trailing.trigger:
            candidate = _trailed_stop(
                risk.trailing, long, as_price(risk.initial_sl), favourable, best
            )
            if candidate is not None and (
                stop is None or (candidate > stop if long else candidate < stop)
            ):
                stop = candidate

    pnl = 0.0 if entry is None else (ltp - entry if long else entry - ltp) * risk.quantity
    reason, detail = _breach(risk, long, ltp, stop, target)
    if reason is None and stop != previous_stop:
        detail = f"trailing stop moved from {previous_stop} to {stop}"

    return RiskDecision(
        evaluated=True,
        breached=reason is not None,
        reason=reason,
        detail=detail,
        stop_loss=stop,
        highest_price=highest,
        lowest_price=lowest,
        unrealized_pnl=pnl,
        exit_side=(Side.SELL if long else Side.BUY) if reason is not None else None,
        exit_quantity=risk.quantity if reason is not None else 0,
    )


def validate_position(risk: PositionRisk, reference_price: float | None = None) -> list[str]:
    """Configuration problems, empty when the position is fine to monitor.
    `reference_price` (usually the current price) defaults to the entry price."""
    long = risk.side is Side.BUY
    problems: list[str] = []
    entry = as_price(risk.entry_price)
    if entry is None:
        problems.append("entry price is missing or not a positive number")
    reference = as_price(reference_price) or entry
    stop = as_price(risk.current_sl) or as_price(risk.initial_sl)
    target = as_price(risk.target)
    if reference is not None:
        if stop is not None and (stop >= reference if long else stop <= reference):
            problems.append(
                f"stop loss {stop} is on the wrong side of {reference} and would exit at once"
            )
        if target is not None and (target <= reference if long else target >= reference):
            problems.append(
                f"target {target} is on the wrong side of {reference} and would exit at once"
            )
    if risk.trailing is not None and risk.trailing.mode is TrailMode.STEPPED:
        if as_price(risk.initial_sl) is None:
            problems.append("a stepped trail moves from the initial stop loss, which is not set")
        if risk.trailing.step > risk.trailing.trigger:
            problems.append(
                "stepped trail step is larger than its trigger: each step would give back "
                "more than the move that earned it"
            )
    return problems


def _trailed_stop(
    trailing: TrailingStop,
    long: bool,
    initial_sl: float | None,
    favourable: float,
    best: float,
) -> float | None:
    direction = 1 if long else -1
    if trailing.mode is TrailMode.CONTINUOUS:
        candidate = best - direction * trailing.step
    else:
        if initial_sl is None:
            return None
        steps = math.floor(favourable / trailing.trigger)
        candidate = initial_sl + direction * trailing.step * steps
    # A stop beyond the best price ever traded would fire on the tick it is set.
    candidate = min(candidate, best) if long else max(candidate, best)
    return as_price(candidate)


def _breach(
    risk: PositionRisk, long: bool, ltp: float, stop: float | None, target: float | None
) -> tuple[BreachReason | None, str | None]:
    # Stop before target: when both are crossed within one tick, assume the adverse one.
    if stop is not None and (ltp <= stop if long else ltp >= stop):
        return BreachReason.STOP_LOSS, f"stop loss {stop} hit at {ltp}"
    if target is not None and (ltp >= target if long else ltp <= target):
        return BreachReason.TARGET, f"target {target} hit at {ltp}"
    cap = as_price(risk.capital_cap)
    if cap is not None and ltp * risk.quantity > cap:
        return (
            BreachReason.CAPITAL_CAP,
            f"position value {ltp * risk.quantity} exceeds capital cap {cap}",
        )
    return None, None
