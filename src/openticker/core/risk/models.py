"""Value types for per-position risk (stop loss, target, trailing stop, capital
cap) and strategy-wide risk over several legs (combined stop loss and target,
profit lock, stops to entry, daily loss limit).

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


class LockMode(StrEnum):
    LOCK = "lock"  # the floor stays at `lock`
    LOCK_AND_TRAIL = "lock_and_trail"  # the floor rises `trail_step` per `trail_step` of new peak


@dataclass(frozen=True)
class ProfitLock:
    """Once the strategy's P&L reaches `arm_at`, exit everything if it falls
    back to the floor, which starts at `lock` and never falls."""

    arm_at: float
    lock: float
    mode: LockMode
    trail_step: float | None = None

    def __post_init__(self) -> None:
        if not (math.isfinite(self.arm_at) and self.arm_at > 0):
            raise ValueError(f"profit lock must arm at a positive profit, got {self.arm_at}")
        if not (math.isfinite(self.lock) and 0 <= self.lock < self.arm_at):
            raise ValueError(
                f"locked profit must be zero or more and below {self.arm_at}, got {self.lock}; "
                "a floor at or above the arming profit would exit on the tick it arms"
            )
        if self.mode is LockMode.LOCK_AND_TRAIL:
            if self.trail_step is None or not (
                math.isfinite(self.trail_step) and self.trail_step > 0
            ):
                raise ValueError("lock and trail needs a positive trail step")
        elif self.trail_step is not None:
            raise ValueError("a trail step only applies to lock and trail")


@dataclass(frozen=True)
class StrategyLimits:
    """Rules over a whole strategy's P&L, in rupees. Losses are positive numbers."""

    combined_stop_loss: float | None = None
    combined_target: float | None = None
    lock_profit: ProfitLock | None = None
    # When one leg's stop loss fires, move every other open leg's stop to its
    # entry and stop applying the combined stop loss.
    stops_to_entry_on_leg_stop: bool = False
    daily_loss_limit: float | None = None

    def __post_init__(self) -> None:
        for name in ("combined_stop_loss", "combined_target", "daily_loss_limit"):
            value = getattr(self, name)
            if value is not None and not (math.isfinite(value) and value > 0):
                raise ValueError(f"{name} must be a positive amount, got {value}")


class StrategyStopReason(StrEnum):
    MANUAL = "manual"
    KILL = "kill"
    SCHEDULE = "schedule"
    EXPIRY = "expiry"
    COMBINED_STOP_LOSS = "combined_stop_loss"
    COMBINED_TARGET = "combined_target"
    PROFIT_LOCK = "profit_lock"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    TICK_STALE = "tick_stale"
    RECOVERY_FAILED = "recovery_failed"
    ERROR = "error"
    LEGS_CLOSED = "legs_closed"  # every leg exited on its own rules


@dataclass(frozen=True)
class LegState:
    leg_id: str
    risk: PositionRisk | None  # None once the leg is closed
    realized_pnl: float


@dataclass(frozen=True)
class StrategyRisk:
    """A run's limits and the ratchets carried between evaluations."""

    limits: StrategyLimits
    peak_mtm: float
    lock_floor: float | None  # None until the profit lock arms
    stops_at_entry: bool  # a leg's stop moved the others to entry; combined stop loss is off
    earlier_runs_realized_pnl: float  # this strategy's earlier runs today, for the daily limit


@dataclass(frozen=True)
class LegExit:
    leg_id: str
    reason: BreachReason
    detail: str


@dataclass(frozen=True)
class StrategyDecision:
    """The outcome of one evaluation. `legs`, `peak_mtm`, `lock_floor` and
    `stops_at_entry` are the values to persist for the next one. When
    `exit_all` is set it wins: every open leg closes, whatever `leg_exits` says."""

    evaluated: bool  # False when an open leg has no usable price: strategy rules skipped
    mtm: float | None
    exit_all: StrategyStopReason | None
    detail: str | None
    leg_exits: tuple[LegExit, ...]
    stops_moved_to_entry: tuple[str, ...]
    legs: tuple[LegState, ...]
    peak_mtm: float
    lock_floor: float | None
    stops_at_entry: bool


def as_price(value: float | None) -> float | None:
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    return value
