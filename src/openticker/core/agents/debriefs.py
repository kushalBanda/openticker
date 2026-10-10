"""When the daily debrief is due (ADR 29's agent jobs, for a trading day
instead of a strategy). Pure.

  debrief on? ──no──▶ NOTHING
       │yes
  trading day? ──no──▶ NOTHING
       │yes
  now ≥ the debrief time (15:40 or later)? ──no──▶ WAIT
       │yes
  the day's P&L recorded (after 15:35)? ──no──▶ WAIT
       │yes
  a debrief job or note for the day already? ──yes──▶ NOTHING
       │no
  fills, ended runs, kills or owed checks that day? ──no──▶ QUIET
       │yes                                   (the server writes a one-line note)
  DUE (queue a debrief job)
"""

import re
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum

from openticker.ports.models import EXCHANGE_TIMEZONE

EARLIEST = time(15, 40)  # after the close is recorded (15:35)


class DebriefScheduleError(ValueError):
    pass


class DebriefOutcome(StrEnum):
    NOTHING = "nothing"
    WAIT = "wait"
    QUIET = "quiet"
    DUE = "due"


@dataclass(frozen=True)
class DebriefSchedule:
    at: time  # exchange-local, EARLIEST or later

    def __post_init__(self) -> None:
        if self.at < EARLIEST:
            raise DebriefScheduleError(
                f"the debrief runs at {EARLIEST:%H:%M} or later, after the day's P&L is "
                f"recorded; {self.at:%H:%M} is too early"
            )


@dataclass(frozen=True)
class DayActivity:
    pnl_recorded: bool
    fills: int
    runs_ended: int
    kills: int
    checks_owed: int
    debrief_exists: bool  # a job for the day (any but refused) or its note

    @property
    def quiet(self) -> bool:
        return not (self.fills or self.runs_ended or self.kills or self.checks_owed)


_AT = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


def parse_at(text: str) -> DebriefSchedule:
    """ "16:00" as a schedule."""
    found = _AT.fullmatch(text.strip())
    if found is None:
        raise DebriefScheduleError(f"give the time as HH:MM, exchange time, not {text!r}")
    return DebriefSchedule(time(int(found.group(1)), int(found.group(2))))


def debrief_due(
    schedule: DebriefSchedule | None, now: datetime, is_trading_day: bool, day: DayActivity
) -> DebriefOutcome:
    if schedule is None or not is_trading_day:
        return DebriefOutcome.NOTHING
    if now.astimezone(EXCHANGE_TIMEZONE).time() < schedule.at or not day.pnl_recorded:
        return DebriefOutcome.WAIT
    if day.debrief_exists:
        return DebriefOutcome.NOTHING
    return DebriefOutcome.QUIET if day.quiet else DebriefOutcome.DUE
