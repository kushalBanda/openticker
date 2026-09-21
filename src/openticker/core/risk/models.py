"""Value types for per-position risk: stop loss, target, trailing stop, capital cap.

Prices are absolute. A price that is None, zero, negative or not finite is
treated as absent: nothing on the supported exchanges trades at or below zero,
so such a value is a missing field that arrived as a numeric default. See
ADR 9 in docs/adr.
"""

import math
from dataclasses import dataclass
from enum import StrEnum

from openticker.ports.models import Side


class TrailMode(StrEnum):
    CONTINUOUS = "continuous"  # stop follows the best price seen, `step` behind it
    STEPPED = "stepped"  # stop moves `step` from the initial stop per `trigger` of profit


class BreachReason(StrEnum):
    STOP_LOSS = "stop_loss"
    TARGET = "target"
    CAPITAL_CAP = "capital_cap"


@dataclass(frozen=True)
class TrailingStop:
    mode: TrailMode
    step: float
    trigger: float  # favourable movement required before the stop starts to trail

    def __post_init__(self) -> None:
        if not (math.isfinite(self.step) and self.step > 0):
            raise ValueError(f"trailing step must be a positive number, got {self.step}")
        if not (math.isfinite(self.trigger) and self.trigger >= 0):
            raise ValueError(f"trailing trigger must be zero or more, got {self.trigger}")
        if self.mode is TrailMode.STEPPED and self.trigger == 0:
            raise ValueError("a stepped trail needs a positive trigger")


@dataclass(frozen=True)
class PositionRisk:
    side: Side
    entry_price: float
    quantity: int  # always positive; direction is `side`
    initial_sl: float | None
    current_sl: float | None  # where the stop is now, after any trailing
    target: float | None
    highest_price: float | None  # best price seen, long positions
    lowest_price: float | None  # best price seen, short positions
    capital_cap: float | None  # most notional value the position may reach
    trailing: TrailingStop | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(
                f"quantity must be positive, got {self.quantity}; use `side` for direction"
            )


@dataclass(frozen=True)
class RiskDecision:
    """The outcome of one evaluation. `stop_loss`, `highest_price` and
    `lowest_price` are the values to persist for the next evaluation."""

    evaluated: bool
    breached: bool
    reason: BreachReason | None
    detail: str | None
    stop_loss: float | None
    highest_price: float | None
    lowest_price: float | None
    unrealized_pnl: float
    exit_side: Side | None  # set on breach: the order side that closes the position
    exit_quantity: int


def as_price(value: float | None) -> float | None:
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    return value
