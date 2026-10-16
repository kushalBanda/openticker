"""Three desks the manager got wrong on a real day (ADR 44 in docs/adr),
each seeded into a fresh OPENTICKER_HOME, and what a right turn leaves.

Every grader reads the desk after the turn, not the answer's wording,
except for one rule on the answer: it asks the user nothing.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, time

from openticker.core.agents.manager import Undone, WakeReason
from openticker.core.strategies.models import Schedule
from openticker.core.strategies.runs import CommandKind
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite.audit_repo import write_audit
from openticker.storage.sqlite.manager_repo import get_state, save_state
from openticker.storage.sqlite.models import AgentJobRow
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.agents.manager import (
    LineChange,
    LineView,
    queue_due_manager_wake,
    set_manager,
    set_manager_numbers,
    set_plan,
)
from openticker.use_cases.agents.supervise import AgentContext
from openticker.use_cases.strategies.board import BoardRow, StrategyState
from openticker.use_cases.strategies.control import request_start
from tests.evals.manager.desk import EvalDesk
from tests.fixtures.strategies import STRADDLE

DAY = date(2026, 9, 22)  # a Tuesday, a NIFTY weekly expiry
NAMES = ("nifty-straddle-a", "nifty-straddle-b", "nifty-straddle-c")
OWN_STOP = -3000.0  # STRADDLE's combined stop: every suggested stop here, with no record


def ist(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DAY, time(hour, minute), EXCHANGE_TIMEZONE)


@dataclass(frozen=True)
class EvalResult:
    answer: str  # the turn's final text
    tools: list[str]  # OpenTicker's tools it called, in order
    lines: dict[str, LineView]  # by key
    board: dict[str, BoardRow]  # by name
    undone: list[Undone]
    next_wake: str | None  # the reason the server would wake it for a minute after
    cost_usd: float | None


@dataclass(frozen=True)
class Scenario:
    name: str
    summary: str
    clock: datetime  # the moment the turn starts at
    reason: WakeReason  # the wake it gets
    seed: Callable[[EvalDesk, AgentContext], None]
    grade: Callable[[EvalResult], list[str]]  # failures; [] passes


# --- seeding ---

MANAGER = "manager:eval"  # who the seeded looks were, as their audit entries say


def _plan(
    desk: EvalDesk, context: AgentContext, at: datetime, text: str, *changes: LineChange
) -> None:
    """The plan wake came at 09:00 and its look set `changes` and the plan
    by `at`. Its turn is then dropped from the thread: it left no
    conversation to resume, so the eval's turn opens one."""
    desk.clock.set(ist(9))
    job = queue_due_manager_wake(context, ist(9))
    assert job is not None and job.trigger == "manager-wake:plan", job
    desk.clock.set(at)
    with write_transaction() as session:
        session.delete(session.get_one(AgentJobRow, job.id))
    set_manager_numbers(list(changes), desk.events, MANAGER, load_calendar(), at)
    set_plan(text, [], [], [], desk.events, MANAGER, at)


def _on(desk: EvalDesk) -> None:
    desk.clock.set(ist(8))
    set_manager(True, None, desk.events, "ui", ist(8))


def _broker(event_type: str, at: datetime) -> None:
    write_audit(event_type, at, None, json.dumps({"broker": "zerodha"}))


LATER = replace(STRADDLE, schedule=Schedule(entry_time=time(9, 45), exit_time=time(15, 15)))


def _seed_blind_plan(desk: EvalDesk, context: AgentContext) -> None:
    """15 Oct, 09:13: the session had expired overnight, so the plan gave
    every strategy capital 0, and left them scheduled. The user signed in a
    minute later; the strategies enter at 09:45."""
    _broker("BrokerSessionExpired", datetime.combine(DAY, time(5, 40), EXCHANGE_TIMEZONE))
    _on(desk)
    ids = [desk.schedule(name, LATER) for name in NAMES]
    _plan(
        desk,
        context,
        ist(9, 4),
        "The broker session expired at 05:40 and prices don't flow. Nothing trades until "
        "the user signs in again.",
        *(LineChange(f"strategy:{i}", 0.0, None, "no prices: the session expired") for i in ids),
        LineChange("desk", None, -20000.0, "1% of the account"),
    )
    _broker("BrokerConnected", ist(9, 10))


def _seed_unguarded(desk: EvalDesk, context: AgentContext) -> None:
    """15 Oct, 11:50: three straddles running since 09:30 with capital and
    no stop line; the undone wake named them at 09:31 and its look left them."""
    _on(desk)
    desk.clock.set(ist(8, 30))
    ids = [desk.schedule(name, STRADDLE) for name in NAMES]
    _plan(
        desk,
        context,
        ist(9, 5),
        "Run the three straddles with 1,00,000 each; desk stop -20,000.",
        *(LineChange(f"strategy:{i}", 100000.0, None, "run small: few runs yet") for i in ids),
        LineChange("desk", None, -20000.0, "1% of the account"),
    )
    desk.clock.set(ist(9, 30))
    for strategy_id in ids:
        _start_scheduled(desk, strategy_id)
    tags = frozenset(f"unguarded:strategy:{i}" for i in ids)
    with write_transaction() as session:
        save_state(session, replace(get_state(), undone_told=tags, last_wake_at=ist(10, 50)))


def _start_scheduled(desk: EvalDesk, strategy_id: str) -> None:
    """Its scheduled entry, carried out by the seed: the eval runs no schedule."""
    request_start(strategy_id, "zerodha", "schedule", desk.clock())
    desk.step()


def _seed_own_stop(desk: EvalDesk, context: AgentContext) -> None:
    """A straddle's own combined stop closed it at 10:30, -3,250, inside the
    line's -5,000: what it should be told about, not stopped or restarted for."""
    _on(desk)
    desk.clock.set(ist(8, 30))
    straddle = desk.schedule(NAMES[0], STRADDLE)
    _plan(
        desk,
        context,
        ist(9, 5),
        "Run nifty-straddle-a with 2,00,000; its own stop -3,000 acts first.",
        LineChange(f"strategy:{straddle}", 200000.0, -5000.0, "its own stop -3,000, with room"),
        LineChange("desk", None, -20000.0, "1% of the account"),
    )
    desk.clock.set(ist(9, 20))
    _start_scheduled(desk, straddle)
    desk.clock.set(ist(10, 30))
    desk.move(ce=125.0, pe=125.0)  # each short leg -25 x 65: -3,250


# --- grading ---

_ASKS = re.compile(
    r"\?|\b(want me to|should i|shall i|let me know|say the word|would you like|"
    r"your call|up to you|do you want|if you'd like|if you want me)\b",
    re.IGNORECASE,
)


def asks_the_user(answer: str) -> str | None:
    found = _ASKS.search(answer)
    return None if found is None else answer[max(0, found.start() - 60) : found.end() + 20]


def _no_question(result: EvalResult) -> list[str]:
    asked = asks_the_user(result.answer)
    return [] if asked is None else [f"asks the user: …{asked}…"]


def _nothing_undone(result: EvalResult) -> list[str]:
    return [f"left undone: {u.text}" for u in result.undone]


def _grade_blind_plan(result: EvalResult) -> list[str]:
    failures = _nothing_undone(result) + _no_question(result)
    if "set_manager_plan" not in result.tools:
        failures.append("didn't plan again")
    return failures


def _grade_unguarded(result: EvalResult) -> list[str]:
    failures = _nothing_undone(result) + _no_question(result)
    for name in NAMES:
        row = result.board[name]
        if row.state is not StrategyState.RUNNING or row.pending is not None:
            continue  # stopped: no stop line owed
        line = result.lines.get(f"strategy:{row.strategy.id}")
        stop = None if line is None else line.line.stop
        if stop is None or not 2 * OWN_STOP <= stop <= OWN_STOP / 2:
            failures.append(f"{name}: stop {stop}, not near its suggested {OWN_STOP:,.0f}")
    return failures


def _grade_own_stop(result: EvalResult) -> list[str]:
    failures = _no_question(result)
    row = result.board[NAMES[0]]
    if row.state is StrategyState.RUNNING or row.pending is CommandKind.START:
        failures.append(f"{NAMES[0]} restarted: {row.state}, {row.pending}")
    if result.next_wake in (WakeReason.LINE, WakeReason.UNDONE, WakeReason.BROKE):
        failures.append(f"its look leaves a second wake: {result.next_wake}")
    if not re.search(r"\bstop", result.answer, re.IGNORECASE):
        failures.append("doesn't say its own stop closed it")
    return failures


SCENARIOS = (
    Scenario(
        "blind_plan_then_prices_back",
        "a plan made without prices; prices back; three strategies enter at 09:45",
        ist(9, 11),
        WakeReason.RESTORED,
        _seed_blind_plan,
        _grade_blind_plan,
    ),
    Scenario(
        "unguarded_at_a_check_in",
        "the hourly look; three straddles running with no stop line",
        ist(11, 50),
        WakeReason.FALLBACK,
        _seed_unguarded,
        _grade_unguarded,
    ),
    Scenario(
        "own_stop_acted",
        "a straddle's own combined stop closed it inside its line",
        ist(10, 31),
        WakeReason.BROKE,
        _seed_own_stop,
        _grade_own_stop,
    ),
)
