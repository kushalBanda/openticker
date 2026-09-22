"""Rule-based strategy definitions: legs chosen relative to the market, a
schedule and strategy-wide limits. A definition names no contract; the legs
are resolved to real contracts when a run starts (ADR 20 in docs/adr).

Construction validates the shape; anything wrong raises
`InvalidStrategyError` with a message an agent can act on.
"""

import math
from dataclasses import dataclass, field
from datetime import time
from enum import StrEnum

from openticker.core.calendar.calendar import EQUITY_HOURS, SQUARE_OFF_BEFORE_CLOSE
from openticker.core.risk.models import StrategyLimits
from openticker.ports.models import Exchange, InstrumentType, Side

MAX_LEGS = 10
MAX_LOTS = 50
MAX_STRIKE_OFFSET = 20
WEEKDAYS = frozenset(range(5))  # Monday 0 to Friday 4


class InvalidStrategyError(ValueError):
    pass


class RelativeExpiry(StrEnum):
    WEEKLY = "weekly"  # nearest expiry; needs weekly contracts
    NEXT_WEEK = "next_week"  # the one after it
    MONTHLY = "monthly"  # last expiry of the nearest month
    NEXT_MONTH = "next_month"  # last expiry of the month after


class Horizon(StrEnum):
    INTRADAY = "intraday"  # MIS, closed by the session's square-off at the latest
    POSITIONAL = "positional"  # NRML, carried overnight


@dataclass(frozen=True)
class StrikeSelector:
    """`offset` counts listed strikes from at the money: 0 is ATM, +n is n
    strikes out of the money, -n n strikes in the money, for the leg's own
    option type. `fixed_strike` names a strike instead."""

    offset: int = 0
    fixed_strike: float | None = None

    def __post_init__(self) -> None:
        if abs(self.offset) > MAX_STRIKE_OFFSET:
            raise InvalidStrategyError(
                f"strike offset must be within {MAX_STRIKE_OFFSET} strikes of ATM, got "
                f"{self.offset}"
            )
        if self.fixed_strike is not None:
            if not (math.isfinite(self.fixed_strike) and self.fixed_strike > 0):
                raise InvalidStrategyError(
                    f"fixed strike must be a positive price, got {self.fixed_strike}"
                )
            if self.offset != 0:
                raise InvalidStrategyError("give either a strike offset or a fixed strike")


@dataclass(frozen=True)
class RiskValue:
    """A distance from the leg's entry price, in points or percent of it."""

    value: float
    percent: bool

    def __post_init__(self) -> None:
        if not (math.isfinite(self.value) and self.value > 0):
            raise InvalidStrategyError(f"risk values must be positive, got {self.value}")


@dataclass(frozen=True)
class LegSpec:
    side: Side
    lots: int
    option_type: InstrumentType  # CE, PE or FUT
    expiry: RelativeExpiry
    strike: StrikeSelector | None = None  # options only; None means ATM
    stop_loss: RiskValue | None = None
    target: RiskValue | None = None
    trailing: RiskValue | None = None  # trailing stop distance, trailing from entry

    def __post_init__(self) -> None:
        if not 1 <= self.lots <= MAX_LOTS:
            raise InvalidStrategyError(f"lots must be 1 to {MAX_LOTS}, got {self.lots}")
        if self.option_type not in (InstrumentType.CE, InstrumentType.PE, InstrumentType.FUT):
            raise InvalidStrategyError(f"a leg is a CE, PE or FUT contract, got {self.option_type}")
        if self.option_type is InstrumentType.FUT:
            if self.strike is not None:
                raise InvalidStrategyError("a futures leg has no strike")
            if self.expiry in (RelativeExpiry.WEEKLY, RelativeExpiry.NEXT_WEEK):
                raise InvalidStrategyError(
                    "futures expire monthly; use monthly or next_month for a futures leg"
                )
        if (
            self.side is Side.SELL
            and self.target is not None
            and self.target.percent
            and self.target.value >= 100
        ):
            raise InvalidStrategyError(
                "a sold leg's target in percent must be below 100: a price can't fall "
                "further than to zero"
            )


@dataclass(frozen=True)
class Schedule:
    entry_time: time | None = None  # exchange-local; None means on command only
    exit_time: time | None = None  # square-off
    weekdays: frozenset[int] = field(default_factory=lambda: WEEKDAYS)  # holidays always skipped
    exit_on_expiry: bool = True  # close on the expiry day of the nearest leg

    def __post_init__(self) -> None:
        if not self.weekdays or not self.weekdays <= WEEKDAYS:
            raise InvalidStrategyError(
                f"weekdays must be some of 0 (Monday) to 4 (Friday), got {sorted(self.weekdays)}"
            )
        opens, closes = EQUITY_HOURS
        for name, at in (("entry_time", self.entry_time), ("exit_time", self.exit_time)):
            if at is not None and not opens <= at < closes:
                raise InvalidStrategyError(
                    f"{name} {at:%H:%M} is outside the session, {opens:%H:%M} to {closes:%H:%M}"
                )
        if (
            self.entry_time is not None
            and self.exit_time is not None
            and self.exit_time <= self.entry_time
        ):
            raise InvalidStrategyError(
                f"exit_time {self.exit_time:%H:%M} must be after entry_time {self.entry_time:%H:%M}"
            )


@dataclass(frozen=True)
class OptionsStrategySpec:
    underlying: str  # standardized index or stock symbol, e.g. "NIFTY 50"
    exchange: Exchange  # the underlying's: NSE or BSE
    legs: tuple[LegSpec, ...]
    horizon: Horizon
    schedule: Schedule = field(default_factory=Schedule)
    limits: StrategyLimits = field(default_factory=StrategyLimits)

    def __post_init__(self) -> None:
        if not 1 <= len(self.legs) <= MAX_LEGS:
            raise InvalidStrategyError(f"a strategy has 1 to {MAX_LEGS} legs, got {len(self.legs)}")
        if self.exchange not in (Exchange.NSE, Exchange.BSE):
            raise InvalidStrategyError(
                f"the underlying trades on NSE or BSE (an index or a stock), got {self.exchange}"
            )
        exit_time = self.schedule.exit_time
        latest = _intraday_cutoff()
        if self.horizon is Horizon.INTRADAY and exit_time is not None and exit_time > latest:
            raise InvalidStrategyError(
                f"intraday positions are squared off at {latest:%H:%M}; set exit_time no later "
                "than that, or make the strategy positional"
            )


def leg_id(index: int) -> str:
    """Legs are named by position, from 1."""
    return f"leg{index + 1}"


def _intraday_cutoff() -> time:
    _, closes = EQUITY_HOURS
    minutes = closes.hour * 60 + closes.minute - SQUARE_OFF_BEFORE_CLOSE.seconds // 60
    return time(minutes // 60, minutes % 60)
