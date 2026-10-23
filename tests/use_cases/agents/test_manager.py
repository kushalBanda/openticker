import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest

from openticker.core.agents.choices import FolderKind, RunChoice
from openticker.core.agents.jobs import AgentJobEndReason, Harness
from openticker.core.agents.manager import ManagerError, PlanCall, PlanItem, SetBy
from openticker.core.agents.threads import Folder
from openticker.core.brain.notes import Debrief
from openticker.core.calendar.models import MarketCalendar
from openticker.core.pnl import DayFigure, DayPnl, IntradayPoint
from openticker.core.scripts.models import ScriptSchedule
from openticker.events.subscribers.audit_log import record_event
from openticker.events.types import (
    ManagerNumbersChanged,
    ManagerPlanSet,
    ManagerStalled,
    ManagerSwitched,
    ManagerWoke,
)
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage.sqlite import agent_jobs_repo, agent_threads_repo
from openticker.storage.sqlite.audit_repo import list_audit, write_audit
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.storage.sqlite.manager_repo import get_state, save_state
from openticker.storage.sqlite.models import AgentJobRow
from openticker.storage.sqlite.pnl_repo import upsert_day, upsert_point
from openticker.storage.sqlite.strategies_repo import insert_strategy, write_transaction
from openticker.use_cases.agents.manage import AgentJobBusyError, AgentJobCapError
from openticker.use_cases.agents.manager import (
    LineChange,
    ManagerDayError,
    ManagerOffError,
    UnknownLineError,
    clear_override,
    get_manager,
    get_manager_day,
    list_manager_days,
    queue_due_manager_wake,
    set_manager,
    set_manager_numbers,
    set_next_wake,
    set_plan,
    wake_manager,
)
from openticker.use_cases.agents.supervise import AgentContext, start_next_chat_turn
from openticker.use_cases.agents.threads import recorded_as
from openticker.use_cases.brain.read import UnknownNoteError
from openticker.use_cases.brain.write import write_debrief
from openticker.use_cases.scripts.manage import schedule_script, upload_script
from openticker.use_cases.strategies.control import (
    request_kill,
    request_stop,
    rotate_webhook,
    schedule_strategy,
)
from openticker.use_cases.strategies.define import create_strategy
from openticker.use_cases.strategies.runner import process_commands
from tests.fixtures.events import SET_UP_AT, Recorded
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.strategies import POSITIONAL_STRADDLE, STRADDLE, list_nifty_market
from tests.fixtures.strategy_desk import Desk
from tests.use_cases.agents.test_agent_jobs import SETTINGS, _Events, _Processes
from tests.use_cases.strategies.test_signals import SPEC as SIGNAL_SPEC

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)  # Tuesday 09:30 IST
CALENDAR = MarketCalendar(years=frozenset({2026}), holidays=(), special_sessions=())
MANAGER = "manager:claude:thr_m"
DAY = date(2026, 9, 22)


def _set(events: _Events, who: str, *changes: LineChange):  # type: ignore[no-untyped-def]
    return set_manager_numbers(list(changes), events, who, CALENDAR, NOW)


def test_manager_sets_its_lines() -> None:
    events = _Events()
    stg = insert_strategy("Straddle", STRADDLE, NOW)
    views, kept, _ = _set(
        events,
        MANAGER,
        LineChange(f"strategy:{stg.id}", 600000.0, -6000.0, "median loser -2,880"),
        LineChange("desk", None, -30000.0, "1.2% of the account"),
    )
    assert kept == []
    assert {str(v.line.key): v.line.set_by for v in views} == {
        "desk": SetBy.MANAGER,
        f"strategy:{stg.id}": SetBy.MANAGER,
    }
    straddle = next(v for v in views if v.name == "Straddle")
    assert straddle.line.capital == 600000.0 and straddle.line.triggered_by == MANAGER
    changed = events.of(ManagerNumbersChanged)
    assert len(changed) == 2 and changed[0].name == "Straddle"  # type: ignore[attr-defined]


def test_your_change_wins_and_keeps_the_managers_values() -> None:
    events = _Events()
    _set(events, MANAGER, LineChange("own", 200000.0, -2000.0, "a hedge budget"))
    views, _, _ = _set(events, "ui", LineChange("own", 100000.0, -1000.0))
    line = views[0].line
    assert line.set_by is SetBy.YOU and (line.capital, line.stop) == (100000.0, -1000.0)
    assert (line.manager_capital, line.manager_stop) == (200000.0, -2000.0)
    assert line.reason == "set by you"


def test_manager_change_to_your_line_is_kept_yours() -> None:
    events = _Events()
    _set(events, "ui", LineChange("desk", None, -5000.0))
    views, kept, _ = _set(events, MANAGER, LineChange("desk", None, -3500.0, "tighter on expiry"))
    line = views[0].line
    assert line.set_by is SetBy.YOU and line.stop == -5000.0 and line.manager_stop == -3500.0
    assert [(k.key, k.stop, k.wanted_stop) for k in kept] == [("desk", -5000.0, -3500.0)]
    last = events.of(ManagerNumbersChanged)[-1]
    assert last.kept_yours and last.set_by == "manager"  # type: ignore[attr-defined]
    # The user changing it again keeps what the manager last wanted.
    views, _, _ = _set(events, "ui", LineChange("desk", None, -4000.0))
    assert views[0].line.manager_stop == -3500.0


def test_clear_override_restores_the_managers_values() -> None:
    events = _Events()
    _set(events, MANAGER, LineChange("own", 200000.0, -2000.0, "budget"))
    _set(events, "ui", LineChange("own", 50000.0, None))
    view = clear_override("own", events, "ui", CALENDAR, NOW)
    assert view.line.set_by is SetBy.MANAGER
    assert (view.line.capital, view.line.stop) == (200000.0, -2000.0)
    with pytest.raises(UnknownLineError, match="no numbers of yours"):
        clear_override("own", events, "ui", CALENDAR, NOW)
    with pytest.raises(UnknownLineError):
        clear_override("desk", events, "ui", CALENDAR, NOW)


def test_set_numbers_refuses_unknown_strategy_and_script() -> None:
    with pytest.raises(UnknownLineError, match="no strategy stg_x"):
        _set(_Events(), "ui", LineChange("strategy:stg_x", 1.0, None))
    with pytest.raises(UnknownLineError, match="no script scr_x"):
        _set(_Events(), "ui", LineChange("script:scr_x", 1.0, None))


@pytest.mark.parametrize(
    ("who", "change", "message"),
    [
        (MANAGER, LineChange("desk", None, -1.0, " "), "give the reason"),
        ("ui", LineChange("desk", -1.0, None), "capital is 0 or more"),
        ("ui", LineChange("desk", None, 5.0), "0 or less"),
        ("ui", LineChange("nope", None, None), "a line's key"),
    ],
)
def test_set_numbers_refuses_bad_values(who: str, change: LineChange, message: str) -> None:
    with pytest.raises(ManagerError, match=message):
        _set(_Events(), who, change)


def test_set_numbers_refuses_a_key_twice_and_none() -> None:
    with pytest.raises(ManagerError, match="once per call"):
        _set(_Events(), "ui", LineChange("desk", None, -1.0), LineChange("desk", None, -2.0))
    with pytest.raises(ManagerError, match="at least one"):
        _set(_Events(), "ui")


def test_get_manager_counts_given_without_the_desk() -> None:
    events = _Events()
    _set(events, "ui", LineChange("own", 100.0, None), LineChange("desk", 999.0, None))
    view = get_manager(1_000_000.0, CALENDAR, NOW)
    assert view.given == 100.0 and view.account == 1_000_000.0


OWN_STOP = (
    " Suggested stop -₹3,000: its own combined stop -₹3,000; 0 runs after costs, fewer than 10."
)


def test_get_manager_lists_a_strategy_trading_without_a_stop_line() -> None:
    desk = Desk()
    running = desk.start(STRADDLE)
    later = insert_strategy("Later straddle", STRADDLE, desk.now)  # enters at 09:20
    schedule_strategy(later.id, "fake", Recorded(), "you", SET_UP_AT)

    view = get_manager(1_000_000.0, CALENDAR, _ist(9, 10))
    assert {(u.key, u.text) for u in view.undone} == {
        (f"strategy:{running}", f"straddle: running, no stop line.{OWN_STOP}"),
        (f"strategy:{later.id}", f"Later straddle: enters 09:20, no stop line.{OWN_STOP}"),
    }

    _set(_Events(), MANAGER, LineChange(f"strategy:{running}", 50_000.0, -2000.0, "its record"))
    _set(_Events(), "ui", LineChange(f"strategy:{later.id}", 50_000.0, None, "mine"))
    assert get_manager(1_000_000.0, CALENDAR, _ist(9, 10)).undone == []


def test_get_manager_says_a_strategy_whose_alert_script_wont_run_is_starved() -> None:
    upsert_instruments([FAKE_INSTRUMENT])
    list_nifty_market()
    alerts = create_strategy("alerts", SIGNAL_SPEC, NOW)
    token = rotate_webhook(alerts.id, "fake", [], NOW)[2]
    script = upload_script("alerts-feed", f'TOKEN = "{token}"\nprint(TOKEN)\n', NOW)
    upload_script("unrelated", 'print("hi")\n', NOW)

    (item,) = [
        u for u in get_manager(1_000_000.0, CALENDAR, NOW).undone if u.kind.value == "starved"
    ]
    assert (item.key, item.name) == (f"strategy:{alerts.id}", "alerts")
    assert "(alerts-feed)" in item.text

    schedule_script(script.id, ScriptSchedule(time(9, 45)), Recorded(), "you", SET_UP_AT)
    left = get_manager(1_000_000.0, CALENDAR, NOW).undone
    assert [u.kind.value for u in left] == ["unguarded"]

    set_manager(True, None, _Events(), "ui", NOW)
    _set(_Events(), MANAGER, LineChange(f"script:{script.id}", 0.0, None, "held today"))
    assert {u.kind.value for u in get_manager(1_000_000.0, CALENDAR, NOW).undone} == {"starved"}


def test_get_manager_says_a_strategy_it_killed_yesterday_is_still_locked() -> None:
    desk = Desk()
    strategy_id = desk.start(STRADDLE)
    request_kill(strategy_id, MANAGER, NOW - timedelta(days=1))
    other = desk.start(STRADDLE, name="other")
    request_kill(other, "ui", NOW - timedelta(days=1))
    process_commands(desk.context, NOW)

    left = get_manager(1_000_000.0, CALENDAR, NOW).undone
    assert [(u.key, u.kind.value) for u in left] == [(f"strategy:{strategy_id}", "locked")]


def test_set_numbers_returns_whats_still_undone() -> None:
    desk = Desk()
    first = desk.start(STRADDLE)
    second = desk.start(STRADDLE, name="second")
    set_manager(True, None, _Events(), "ui", NOW)  # a line holds only while it is on
    _, _, left = _set(_Events(), MANAGER, LineChange(f"strategy:{first}", 0.0, None, "no evidence"))
    assert {(u.key, u.kind.value) for u in left} == {
        (f"strategy:{first}", "contradicted"),
        (f"strategy:{second}", "unguarded"),
    }
    contradicted = next(u for u in left if u.key == f"strategy:{first}")
    assert "but your line gives it capital 0. Run " in contradicted.text


def test_a_stop_set_past_todays_figure_does_not_wake_it(tmp_path: Path) -> None:
    events = _Events()
    context = _planned(tmp_path, events)
    desk = Desk()
    desk.now -= timedelta(days=1)
    strategy_id = desk.start(POSITIONAL_STRADDLE)
    desk.now += timedelta(days=1)
    desk.tick(ce=110.0, pe=110.0)
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)  # its own stop acted: -1,300 today
    key = f"strategy:{strategy_id}"
    _set(events, MANAGER, LineChange(key, 0.0, -1000.0, "the loss it took"))

    assert key in get_state().crossed
    assert queue_due_manager_wake(context, _ist(10)) is None  # no line wake for it


def test_a_wake_names_whats_undone(tmp_path: Path) -> None:
    context = _planned(tmp_path, _Events())
    Desk().start(STRADDLE)
    set_next_wake(_ist(10), "the 10:00 data", CALENDAR, _ist(9, 30))

    job = queue_due_manager_wake(context, _ist(10))

    assert job is not None
    assert f"<undone>\n- straddle: running, no stop line.{OWN_STOP}\n</undone>" in (
        job.prompt or ""
    )


def test_recorded_as_manager_for_a_manager_thread_chat_key() -> None:
    with write_transaction() as session:
        thread = agent_threads_repo.add_thread(
            session, Folder.MANAGER, date(2026, 9, 22).isoformat(), Harness.CLAUDE, "Desk", NOW
        )
        general = agent_threads_repo.add_thread(
            session, Folder.GENERAL, None, Harness.CODEX, "Hi", NOW
        )
    assert recorded_as(f"chat:{thread.id}") == f"manager:claude:{thread.id}"
    assert recorded_as(f"chat:{general.id}") == f"chat:codex:{general.id}"


def _ist(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 22, hour, minute, tzinfo=EXCHANGE_TIMEZONE)


def _end_turns(
    now: datetime, reason: AgentJobEndReason = AgentJobEndReason.FINISHED, detail: str = "done"
) -> None:
    """Ends every open turn of the day, in every thread of it."""
    with write_transaction() as session:
        for thread in agent_threads_repo.manager_threads(DAY, session):
            for job in agent_jobs_repo.turns_of(thread.id, session):
                if job.ended_at is None:
                    agent_jobs_repo.end_job(session, job.id, reason, detail, now)


def _context(tmp_path: Path, events: _Events) -> AgentContext:
    settings = replace(
        SETTINGS,
        choices={
            FolderKind.MANAGER: RunChoice(Harness.CLAUDE, "claude-opus-5-5", "high"),
            FolderKind.MANAGER_CHECKS: RunChoice(
                Harness.CLAUDE, "claude-sonnet-5-5", "low", max_budget_usd=0.25
            ),
        },
    )
    return AgentContext(_Processes(), events, settings, tmp_path, "http://127.0.0.1:8750/mcp")


def test_queue_does_nothing_while_off(tmp_path: Path) -> None:
    assert queue_due_manager_wake(_context(tmp_path, _Events()), _ist(9)) is None
    assert agent_threads_repo.manager_threads(DAY) == []


def test_queue_opens_todays_thread_with_a_plan_turn(tmp_path: Path) -> None:
    events = _Events()
    set_manager(True, None, events, "ui", _ist(8))
    context = _context(tmp_path, events)
    assert queue_due_manager_wake(context, _ist(8, 59)) is None
    job = queue_due_manager_wake(context, _ist(9))
    assert job is not None and job.trigger == "manager-wake:plan"
    assert job.prompt is not None and job.prompt.startswith('<wake reason="plan"')
    assert "Plan today, Tue 22 Sep 2026" in job.prompt
    assert (job.model, job.effort) == ("claude-opus-5-5", "high")
    [*_, thread] = agent_threads_repo.manager_threads(DAY)
    assert thread is not None and job.thread_id == thread.id and thread.folder is Folder.MANAGER
    woke = events.of(ManagerWoke)
    assert [(w.reason, w.thread_id) for w in woke] == [("plan", thread.id)]  # type: ignore[attr-defined]
    assert queue_due_manager_wake(context, _ist(9, 1)) is None  # its turn still waits


def test_queue_wakes_at_the_time_it_set_then_falls_back_then_closes(tmp_path: Path) -> None:
    events = _Events()
    set_manager(True, None, events, "ui", _ist(8))
    context = _context(tmp_path, events)
    queue_due_manager_wake(context, _ist(9))
    _end_turns(_ist(9, 5))
    set_next_wake(_ist(11, 40), "after the 11:30 data", CALENDAR, _ist(9, 5))
    assert queue_due_manager_wake(context, _ist(11, 39)) is None
    scheduled = queue_due_manager_wake(context, _ist(11, 40))
    assert scheduled is not None and scheduled.trigger == "manager-wake:scheduled"
    assert "after the 11:30 data" in (scheduled.prompt or "")
    assert get_state().next_wake_at is None
    _end_turns(_ist(11, 45))
    assert queue_due_manager_wake(context, _ist(12, 39)) is None
    fallback = queue_due_manager_wake(context, _ist(12, 40))
    assert fallback is not None and fallback.trigger == "manager-wake:fallback"
    _end_turns(_ist(12, 45))
    close = queue_due_manager_wake(context, _ist(15, 35))
    assert close is not None and close.trigger == "manager-wake:close"
    _end_turns(_ist(15, 40))
    assert queue_due_manager_wake(context, _ist(16, 40)) is None
    assert get_state().closed_on == DAY
    assert {t.thread_id for t in (scheduled, fallback, close)} == {scheduled.thread_id}


def test_check_ins_run_on_their_own_choice_and_decisive_looks_on_the_managers(
    tmp_path: Path,
) -> None:
    events = _Events()
    set_manager(True, None, events, "ui", _ist(8))
    context = _context(tmp_path, events)
    plan = queue_due_manager_wake(context, _ist(9))
    _end_turns(_ist(9, 5))
    set_next_wake(_ist(11), "after the 11:00 data", CALENDAR, _ist(9, 5))
    scheduled = queue_due_manager_wake(context, _ist(11))
    _end_turns(_ist(11, 5))
    fallback = queue_due_manager_wake(context, _ist(12, 5))
    _end_turns(_ist(12, 10))
    close = queue_due_manager_wake(context, _ist(15, 35))

    looks = [plan, scheduled, fallback, close]
    assert all(look is not None for look in looks)
    assert [(look.model, look.effort) for look in looks if look] == [
        ("claude-opus-5-5", "high"),
        ("claude-sonnet-5-5", "low"),
        ("claude-sonnet-5-5", "low"),
        ("claude-opus-5-5", "high"),
    ]
    assert len({look.thread_id for look in looks if look}) == 1  # one conversation


def test_a_check_in_launches_with_its_own_spend_cap(tmp_path: Path) -> None:
    context = _planned(tmp_path, _Events())
    scheduled = queue_due_manager_wake(context, _ist(14))
    assert scheduled is not None and scheduled.thread_id is not None
    with write_transaction() as session:
        agent_threads_repo.set_session(session, scheduled.thread_id, "sess-day")

    start_next_chat_turn(context, _ist(14))

    assert context.processes.launches[-1].max_budget_usd == 0.25  # type: ignore[attr-defined]


def test_a_retried_plan_stays_a_decisive_look(tmp_path: Path) -> None:
    events = _Events()
    set_manager(True, None, events, "ui", _ist(8))
    context = _context(tmp_path, events)
    assert queue_due_manager_wake(context, _ist(9)) is not None
    _end_turns(_ist(9, 1), FAILED, "exited 1: overloaded")

    again = queue_due_manager_wake(context, _ist(9, 6))

    assert again is not None and again.trigger == "manager-wake:plan"
    assert (again.model, again.effort) == ("claude-opus-5-5", "high")


def test_turning_off_stops_future_wakes(tmp_path: Path) -> None:
    events = _Events()
    set_manager(True, 12, events, "ui", _ist(8))
    set_manager(False, None, events, "ui", _ist(8, 30))
    assert get_state().wakes_per_day == 12
    assert queue_due_manager_wake(_context(tmp_path, events), _ist(9)) is None
    switched = events.of(ManagerSwitched)
    assert [s.enabled for s in switched] == [True, False]  # type: ignore[attr-defined]
    with pytest.raises(ManagerError, match="1 to 200"):
        set_manager(True, 0, events, "ui", _ist(8))


def test_set_next_wake_validates_and_replaces() -> None:
    set_next_wake(_ist(11), "first", CALENDAR, _ist(10))
    set_next_wake(_ist(12), "second", CALENDAR, _ist(10))
    state = get_state()
    assert (state.next_wake_at, state.next_wake_reason) == (_ist(12), "second")
    with pytest.raises(ManagerError, match="say why"):
        set_next_wake(_ist(12), " ", CALENDAR, _ist(10))
    with pytest.raises(ManagerError, match="at least 2 minutes"):
        set_next_wake(_ist(10, 1), "soon", CALENDAR, _ist(10))


def test_set_plan_refuses_unknown_lesson_and_keeps_the_plan() -> None:
    events = _Events()
    with pytest.raises(UnknownNoteError, match="no lesson les_x"):
        set_plan("Run small.", [], [], ["les_x"], events, MANAGER, _ist(9))
    plan = set_plan("Run small on expiry.", [], [], [], events, MANAGER, _ist(9))
    assert get_state().plan == plan and plan.day == DAY
    assert [p.text for p in events.of(ManagerPlanSet)] == ["Run small on expiry."]  # type: ignore[attr-defined]


def test_set_plan_names_each_call_and_keeps_them() -> None:
    events = _Events()
    stg = insert_strategy("Straddle", STRADDLE, NOW)
    with pytest.raises(UnknownLineError, match="no strategy stg_x"):
        set_plan(
            "Nothing new.",
            [PlanItem("strategy:stg_x", PlanCall.SITS_OUT, "gone")],
            [],
            [],
            events,
            MANAGER,
            _ist(9),
        )
    plan = set_plan(
        " Straddle runs small. ",
        [
            PlanItem(f" strategy:{stg.id}", PlanCall.RUNS, " half its capital "),
            PlanItem("own", PlanCall.SITS_OUT, "no edge today"),
        ],
        [" RELIANCE CNC has no stop "],
        [],
        events,
        MANAGER,
        _ist(9),
    )
    assert plan.text == "Straddle runs small."
    assert plan.items == (
        PlanItem(f"strategy:{stg.id}", PlanCall.RUNS, "half its capital", "Straddle"),
        PlanItem("own", PlanCall.SITS_OUT, "no edge today"),
    )
    assert plan.watch == ("RELIANCE CNC has no stop",)
    assert get_state().plan == plan
    set_ = events.of(ManagerPlanSet)[-1]
    record_event(replace(set_, occurred_at=_ist(9)))  # type: ignore[type-var]
    assert get_manager_day(DAY, CALENDAR, NOW + timedelta(days=1)).plan == plan


def _planned(tmp_path: Path, events: _Events) -> AgentContext:
    """On, with the day planned and its turn over."""
    set_manager(True, None, events, "ui", _ist(8))
    context = _context(tmp_path, events)
    assert queue_due_manager_wake(context, _ist(9)) is not None
    _end_turns(_ist(9, 5))
    set_next_wake(_ist(14), "the afternoon", CALENDAR, _ist(9, 5))
    return context


def _stopped(reason: str, at: datetime, name: str = "Straddle") -> None:
    payload = {"name": name, "strategy_id": "stg_1", "reason": reason, "realized_pnl": -6240.5}
    write_audit("StrategyStopped", at, "strategy:stg_1", json.dumps(payload))


def _broker(event_type: str, at: datetime) -> None:
    write_audit(event_type, at, None, json.dumps({"broker": "zerodha"}))


def test_queue_wakes_restored_when_the_user_signs_in_after_a_blind_plan(tmp_path: Path) -> None:
    events = _Events()
    _broker("BrokerSessionExpired", datetime(2026, 9, 21, 20, 0, tzinfo=EXCHANGE_TIMEZONE))
    context = _planned(tmp_path, events)
    set_plan("Nothing trades: no prices.", [], [], [], events, MANAGER, _ist(9, 4))
    assert queue_due_manager_wake(context, _ist(9, 10)) is None  # still down

    _broker("BrokerConnected", _ist(9, 18))
    job = queue_due_manager_wake(context, _ist(9, 19))

    assert job is not None and job.trigger == "manager-wake:restored"
    assert "Your plan at 09:04 was made while prices were down; they came back at 09:18." in (
        job.prompt or ""
    )
    _end_turns(_ist(9, 25))
    again = queue_due_manager_wake(context, _ist(9, 26))
    assert again is None or again.trigger != "manager-wake:restored"  # once


def test_a_plan_made_with_prices_is_not_blind(tmp_path: Path) -> None:
    events = _Events()
    _broker("BrokerSessionExpired", datetime(2026, 9, 21, 20, 0, tzinfo=EXCHANGE_TIMEZONE))
    _broker("BrokerConnected", _ist(8, 50))
    context = _planned(tmp_path, events)
    set_plan("Run small.", [], [], [], events, MANAGER, _ist(9, 4))
    _broker("BrokerConnected", _ist(9, 18))  # signed in again
    assert queue_due_manager_wake(context, _ist(9, 19)) is None


def test_queue_wakes_undone_when_a_look_left_a_strategy_unguarded(tmp_path: Path) -> None:
    context = _planned(tmp_path, _Events())
    Desk().start(STRADDLE)

    job = queue_due_manager_wake(context, _ist(10))

    assert job is not None and job.trigger == "manager-wake:undone"
    assert "- straddle: running, no stop line." in (job.prompt or "")
    _end_turns(_ist(10, 5))
    assert queue_due_manager_wake(context, _ist(10, 10)) is None  # named once


def test_turning_on_does_not_wake_for_what_broke_before(tmp_path: Path) -> None:
    _stopped("kill", _ist(7))
    context = _planned(tmp_path, _Events())
    assert queue_due_manager_wake(context, _ist(10)) is None


def test_plan_is_told_what_broke_since_the_last_close_even_before_it_was_on(
    tmp_path: Path,
) -> None:
    monday = datetime(2026, 9, 21, 20, 0, tzinfo=EXCHANGE_TIMEZONE)
    write_audit("BrokerSessionExpired", monday, None, json.dumps({"broker": "zerodha"}))
    _stopped("tick_stale", _ist(7))
    _stopped("tick_stale", _ist(7), "Futures trend")
    _stopped("kill", datetime(2026, 9, 21, 15, 0, tzinfo=EXCHANGE_TIMEZONE))  # before the close
    set_manager(True, None, _Events(), "ui", _ist(8))
    job = queue_due_manager_wake(_context(tmp_path, _Events()), _ist(9))
    assert job is not None and job.prompt is not None
    since = job.prompt.split("<since_last_close", 1)[1].split("</since_last_close>", 1)[0]
    assert 'from="Mon 21 Sep 15:30"' in since
    assert "- Mon 21 Sep 20:00 The zerodha session expired" in since
    assert (
        "- 07:00 2 strategies stopped: tick_stale, realized -12,481.00 together: "
        "Straddle, Futures trend." in since
    )
    assert "kill" not in since
    assert "No close answer" in job.prompt


def test_plan_carries_the_answer_it_gave_at_the_last_close(tmp_path: Path) -> None:
    monday = date(2026, 9, 21)

    def at(hour: int, minute: int = 0) -> datetime:
        return datetime.combine(monday, time(hour, minute), EXCHANGE_TIMEZONE)

    context = _context(tmp_path, _Events())
    set_manager(True, None, _Events(), "ui", at(8))
    assert queue_due_manager_wake(context, at(9)) is not None
    with write_transaction() as session:
        for thread in agent_threads_repo.manager_threads(monday, session):
            for turn in agent_jobs_repo.turns_of(thread.id, session):
                agent_jobs_repo.end_job(
                    session, turn.id, AgentJobEndReason.FINISHED, "done", at(9, 5)
                )
    close = queue_due_manager_wake(context, at(15, 35))
    assert close is not None and close.trigger == "manager-wake:close"
    with write_transaction() as session:
        agent_jobs_repo.end_job(
            session,
            close.id,
            AgentJobEndReason.FINISHED,
            "done",
            at(15, 36),
            summary="Desk ended -₹1,200. Tomorrow: smaller straddle.",
        )
    plan = queue_due_manager_wake(context, _ist(9))
    assert plan is not None and plan.prompt is not None
    assert (
        '<yesterdays_close day="Mon 21 Sep 2026">\nDesk ended -₹1,200. Tomorrow: smaller straddle.'
        in plan.prompt
    )


def test_queue_wakes_once_for_what_broke_and_names_it(tmp_path: Path) -> None:
    events = _Events()
    context = _planned(tmp_path, events)
    _stopped("kill", _ist(10))
    _stopped("daily_loss_limit", _ist(10), "Futures trend")
    job = queue_due_manager_wake(context, _ist(10, 1))
    assert job is not None and job.trigger == "manager-wake:broke"
    assert "Strategy 'Straddle' (stg_1) stopped: kill, realized -6,240.50." in (job.prompt or "")
    assert "'Futures trend'" in (job.prompt or "")
    _end_turns(_ist(10, 5))
    assert queue_due_manager_wake(context, _ist(10, 6)) is None
    assert get_state().next_wake_at == _ist(14)  # its own time still stands


def test_what_broke_while_it_works_wakes_it_after(tmp_path: Path) -> None:
    context = _planned(tmp_path, _Events())
    set_next_wake(_ist(10), "soon", CALENDAR, _ist(9, 30))
    assert queue_due_manager_wake(context, _ist(10)) is not None
    _stopped("error", _ist(10, 1))
    assert queue_due_manager_wake(context, _ist(10, 2)) is None  # its turn is still open
    _end_turns(_ist(10, 3))
    job = queue_due_manager_wake(context, _ist(10, 4))
    assert job is not None and job.trigger == "manager-wake:broke"


def test_queue_does_not_wake_for_a_manual_stop(tmp_path: Path) -> None:
    context = _planned(tmp_path, _Events())
    _stopped("manual", _ist(10))
    assert queue_due_manager_wake(context, _ist(10, 1)) is None
    passed = get_state().last_audit_id
    assert passed == max(e.id for e in list_audit(10))  # judged, not read again


def test_queue_wakes_on_line_crossed_once_until_it_recovers(tmp_path: Path) -> None:
    events = _Events()
    context = _planned(tmp_path, events)
    _set(events, MANAGER, LineChange("desk", None, -1000.0, "1% of the day"))

    def point(minute: int, net: float) -> None:
        upsert_point(DAY, IntradayPoint(time(10, minute), net, net, 0.0, 0.0))

    point(0, -900.0)
    assert queue_due_manager_wake(context, _ist(10)) is None
    point(1, -1000.0)
    job = queue_due_manager_wake(context, _ist(10, 1))
    assert job is not None and job.trigger == "manager-wake:line"
    assert "The desk is at -₹1,000.00 today, at or past your stop -₹1,000.00." in (job.prompt or "")
    _end_turns(_ist(10, 2))
    point(3, -1200.0)
    assert queue_due_manager_wake(context, _ist(10, 3)) is None  # still crossed: no news
    point(4, -800.0)
    assert queue_due_manager_wake(context, _ist(10, 4)) is None  # recovered
    point(5, -1100.0)
    again = queue_due_manager_wake(context, _ist(10, 5))
    assert again is not None and again.trigger == "manager-wake:line"


def test_a_positional_run_closed_today_at_a_loss_crosses_its_line(tmp_path: Path) -> None:
    events = _Events()
    context = _planned(tmp_path, events)
    desk = Desk()
    desk.now -= timedelta(days=1)  # entered yesterday, carried overnight
    strategy_id = desk.start(POSITIONAL_STRADDLE)
    desk.now += timedelta(days=1)
    desk.tick(ce=110.0, pe=110.0)
    _set(events, MANAGER, LineChange(f"strategy:{strategy_id}", None, -1000.0, "half a lot's risk"))
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)  # bought back today: -1,300

    job = queue_due_manager_wake(context, _ist(10))

    assert job is not None and job.trigger == "manager-wake:line"
    assert f"'straddle' ({strategy_id}) is at -₹1,300.00 today, at or past your stop" in (
        job.prompt or ""
    )


FAILED = AgentJobEndReason.FAILED


def test_a_failed_turn_is_tried_again_after_5_minutes(tmp_path: Path) -> None:
    context = _planned(tmp_path, _Events())
    set_next_wake(_ist(10), "the 10:00 data", CALENDAR, _ist(9, 30))
    first = queue_due_manager_wake(context, _ist(10))
    assert first is not None
    _end_turns(_ist(10, 1), FAILED, "exited 1: overloaded")
    assert queue_due_manager_wake(context, _ist(10, 5)) is None
    again = queue_due_manager_wake(context, _ist(10, 6))
    assert again is not None and again.trigger == "manager-wake:scheduled"
    assert again.prompt == f"Retry: your last turn failed (exited 1: overloaded).\n{first.prompt}"
    _end_turns(_ist(10, 7), FAILED, "exited 1")
    third = queue_due_manager_wake(context, _ist(10, 12))
    assert third is not None and third.prompt is not None
    assert third.prompt.startswith(
        'Retry: your last 2 turns failed (exited 1).\n<wake reason="scheduled"'
    )
    assert third.prompt.count("Retry:") == 1


def test_queue_publishes_stalled_once_after_three_failures(tmp_path: Path) -> None:
    events = _Events()
    context = _planned(tmp_path, events)
    at = _ist(10)
    set_next_wake(at, "look", CALENDAR, _ist(9, 30))
    for _ in range(3):
        assert queue_due_manager_wake(context, at) is not None
        _end_turns(at, AgentJobEndReason.TIMEOUT, "ran past 15 minutes")
        at = at.replace(minute=at.minute + 5)
    assert queue_due_manager_wake(context, _ist(10, 16)) is None  # now every 30 minutes
    assert queue_due_manager_wake(context, _ist(10, 20)) is None
    stalled = events.of(ManagerStalled)
    assert [s.why for s in stalled] == ["failing"]  # type: ignore[attr-defined]
    assert "Its last 3 turns failed (latest: ran past 15 minutes)" in stalled[0].detail  # type: ignore[attr-defined]
    assert get_state().stalled == "failing"
    retry = queue_due_manager_wake(context, _ist(10, 40))
    assert retry is not None
    _end_turns(_ist(10, 45))
    assert queue_due_manager_wake(context, _ist(10, 46)) is None
    assert get_state().stalled is None  # a finished turn clears it


def test_queue_publishes_capped_once_a_day(tmp_path: Path) -> None:
    events = _Events()
    set_manager(True, 2, events, "ui", _ist(8))
    context = _context(tmp_path, events)
    assert queue_due_manager_wake(context, _ist(9)) is not None
    _end_turns(_ist(9, 5))
    _stopped("kill", _ist(9, 20))
    assert queue_due_manager_wake(context, _ist(9, 21)) is not None
    _end_turns(_ist(9, 25))
    _stopped("kill", _ist(9, 30))
    assert queue_due_manager_wake(context, _ist(9, 31)) is None
    assert queue_due_manager_wake(context, _ist(9, 32)) is None
    capped = events.of(ManagerStalled)
    assert [s.why for s in capped] == ["capped"]  # type: ignore[attr-defined]
    assert "used its 2 wakes today" in capped[0].detail  # type: ignore[attr-defined]
    # Raised, it goes on, and what broke while capped wakes it.
    set_manager(True, 3, events, "ui", _ist(9, 33))
    job = queue_due_manager_wake(context, _ist(9, 34))
    assert job is not None and job.trigger == "manager-wake:broke"


def test_queue_opens_a_fresh_thread_after_a_sessionless_first_turn(tmp_path: Path) -> None:
    events = _Events()
    set_manager(True, None, events, "ui", _ist(8))
    context = _context(tmp_path, events)
    first = queue_due_manager_wake(context, _ist(9))
    assert first is not None
    _end_turns(_ist(9), AgentJobEndReason.START_FAILED, "claude not found")
    assert queue_due_manager_wake(context, _ist(9, 4)) is None
    second = queue_due_manager_wake(context, _ist(9, 5))
    assert second is not None and second.trigger == "manager-wake:plan"
    assert second.thread_id != first.thread_id
    assert (second.prompt or "").startswith("Retry: your last turn failed (claude not found).")
    assert [t.id for t in agent_threads_repo.manager_threads(DAY)] == [
        first.thread_id,
        second.thread_id,
    ]
    # every thread of the day counts
    assert get_manager(1_000_000.0, CALENDAR, _ist(9, 5)).wakes_today == 2


def test_failed_turn_with_a_conversation_retries_in_the_same_thread(tmp_path: Path) -> None:
    context = _planned(tmp_path, _Events())
    [*_, thread] = agent_threads_repo.manager_threads(DAY)
    assert thread is not None
    with write_transaction() as session:
        agent_threads_repo.set_session(session, thread.id, "sess_1")
    _stopped("kill", _ist(10))
    assert queue_due_manager_wake(context, _ist(10, 1)) is not None
    _end_turns(_ist(10, 2), FAILED, "exited 1")
    again = queue_due_manager_wake(context, _ist(10, 7))
    assert again is not None and again.thread_id == thread.id
    assert again.trigger == "manager-wake:broke"
    assert "Strategy 'Straddle' (stg_1) stopped: kill" in (again.prompt or "")


def test_wake_manager_refused_when_off_or_busy(tmp_path: Path) -> None:
    events = _Events()
    with pytest.raises(ManagerOffError, match="turn it on"):
        wake_manager(SETTINGS, events, "ui", _ist(10))
    set_manager(True, None, events, "ui", _ist(8))
    job = wake_manager(SETTINGS, events, "ui", _ist(10))
    assert job.trigger == "manager-wake:asked"
    assert (
        job.prompt == '<wake reason="asked" day="2026-09-22">\n</wake>\n'
        "The user asked you to look now: a full look, as the skill's plan reads the desk, and "
        "act if it needs it."
    )
    assert [w.reason for w in events.of(ManagerWoke)] == ["asked"]  # type: ignore[attr-defined]
    with pytest.raises(AgentJobBusyError, match="already looking"):
        wake_manager(SETTINGS, events, "ui", _ist(10, 1))
    _end_turns(_ist(10, 2))
    # Look now works after the close wake, too.
    with write_transaction() as session:
        save_state(session, replace(get_state(session), closed_on=DAY))
    assert wake_manager(SETTINGS, events, "ui", _ist(16)).thread_id == job.thread_id


def test_wake_manager_counts_against_the_cap(tmp_path: Path) -> None:
    events = _Events()
    set_manager(True, 1, events, "ui", _ist(8))
    wake_manager(SETTINGS, events, "ui", _ist(10))
    _end_turns(_ist(10, 1))
    with pytest.raises(AgentJobCapError, match="used its 1 wakes"):
        wake_manager(SETTINGS, events, "ui", _ist(10, 2))


# --- its days, read back (ADR 43) ---


def test_manager_day_reads_back_a_past_day_it_ran(tmp_path: Path) -> None:
    _planned(tmp_path, _Events())
    [thread] = agent_threads_repo.manager_threads(DAY)
    day = get_manager_day(DAY, CALENDAR, datetime(2026, 9, 23, 10, 0, tzinfo=EXCHANGE_TIMEZONE))
    assert (day.trading_date, day.live, day.ran, day.thread_ids) == (DAY, False, True, [thread.id])
    assert get_manager_day(DAY, CALENDAR, _ist(10)).live


def test_manager_day_refuses_a_weekend_and_a_day_to_come() -> None:
    with pytest.raises(ManagerDayError, match="wasn't a trading day"):
        get_manager_day(date(2026, 9, 20), CALENDAR, NOW)
    with pytest.raises(ManagerDayError, match="hasn't happened yet"):
        get_manager_day(date(2026, 9, 23), CALENDAR, NOW)


def test_list_manager_days_lists_trading_days_and_where_it_ran(tmp_path: Path) -> None:
    _planned(tmp_path, _Events())
    days = list_manager_days(date(2026, 9, 17), date(2026, 9, 30), CALENDAR, _ist(10))
    assert [(d.trading_date.day, d.ran) for d in days] == [
        (17, False),
        (18, False),  # 19 and 20 are a weekend
        (21, False),
        (22, True),  # cut at today
    ]


def test_list_manager_days_refuses_a_backwards_or_too_long_range() -> None:
    with pytest.raises(ManagerError, match="is after"):
        list_manager_days(DAY, date(2026, 9, 1), CALENDAR, NOW)
    with pytest.raises(ManagerError, match="at most 60 days"):
        list_manager_days(date(2026, 7, 1), DAY, CALENDAR, NOW)


def test_manager_day_desk_from_the_record_else_the_last_minute_else_none() -> None:
    upsert_day(DayPnl(date(2026, 9, 18), -7015.5, 1587.23, -7243.25, -15845.98, 0.0, 30, True), NOW)
    upsert_point(date(2026, 9, 21), IntradayPoint(time(9, 20), 10.0, 0.0, 0.0, 10.0))
    upsert_point(date(2026, 9, 21), IntradayPoint(time(15, 29), -30.0, 400.0, 80.0, -350.0))
    recorded = get_manager_day(date(2026, 9, 18), CALENDAR, NOW).desk
    assert recorded == DayFigure(-7015.5, 1587.23, -7243.25) and recorded.net == -15845.98
    assert get_manager_day(date(2026, 9, 21), CALENDAR, NOW).desk == DayFigure(400.0, 80.0, -350.0)
    assert get_manager_day(date(2026, 9, 17), CALENDAR, NOW).desk is None


def test_manager_day_counts_its_looks_and_their_cost(tmp_path: Path) -> None:
    _planned(tmp_path, _Events())
    [turn] = agent_jobs_repo.turns_of(agent_threads_repo.manager_threads(DAY)[0].id)
    with write_transaction() as session:
        row = session.get(AgentJobRow, turn.id)
        assert row is not None
        row.cost_usd = 0.26
    day = get_manager_day(DAY, CALENDAR, _ist(10))
    assert (day.use.looks, day.use.cost_usd) == (1, 0.26)
    [summary] = [
        d for d in list_manager_days(DAY, DAY, CALENDAR, _ist(10)) if d.trading_date == DAY
    ]
    assert (summary.ran, summary.looks, summary.cost_usd, summary.net) == (True, 1, 0.26, None)


def _logged(key: str, stop: float, set_by: str, at: datetime, kept: bool = False) -> None:
    record_event(
        ManagerNumbersChanged(
            key=key,
            name=None,
            capital=None,
            stop=stop,
            set_by=set_by,
            kept_yours=kept,
            reason="why",
            triggered_by="ui" if set_by == "you" else MANAGER,
            occurred_at=at,
        )
    )


def test_manager_day_reads_the_lines_back_as_they_stood_at_the_close() -> None:
    stg = insert_strategy("Straddle", STRADDLE, NOW)
    upsert_day(DayPnl(DAY, -21000.0, 500.0, -9500.0, -31000.0, 0.0, 9, True), NOW)
    _logged("desk", -30000.0, "manager", _ist(9, 2) - timedelta(days=1))  # yesterday's, carried
    _logged(f"strategy:{stg.id}", -6000.0, "manager", _ist(9, 2))
    _logged(f"strategy:{stg.id}", -4000.0, "you", _ist(11, 20))
    _logged(f"strategy:{stg.id}", -9000.0, "manager", _ist(12, 0), kept=True)
    _logged("desk", -20000.0, "manager", _ist(15, 36))  # the close look's, for tomorrow
    day = get_manager_day(DAY, CALENDAR, NOW + timedelta(days=1))
    desk, straddle = day.lines
    assert (desk.line.stop, desk.figure, desk.crossed) == (-30000.0, day.desk, True)
    assert [(c.stop, c.at > day.close) for c in desk.line.changes] == [(-20000.0, True)]
    assert (straddle.line.stop, straddle.line.set_by) == (-4000.0, SetBy.YOU)
    assert straddle.figure == DayFigure(0.0, 0.0) and not straddle.crossed  # no fills that day
    assert [c.kept_yours for c in straddle.line.changes] == [False, False, True]


def test_manager_day_reads_the_days_plan_and_whether_it_was_debriefed() -> None:
    for on, text, at in (
        (DAY - timedelta(days=1), "Monday's plan", _ist(9, 3) - timedelta(days=1)),
        (DAY, "Run small", _ist(9, 3)),
        (DAY, "Run smaller: the session expired", _ist(13, 52)),
    ):
        record_event(ManagerPlanSet(on, text, ("les_1",), MANAGER, occurred_at=at))
    later = NOW + timedelta(days=1)
    day = get_manager_day(DAY, CALENDAR, later)
    assert day.plan is not None and day.plan.text == "Run smaller: the session expired"
    assert (day.plan.lesson_ids, day.plan.at) == (("les_1",), _ist(13, 52))
    assert not day.debrief
    write_debrief(
        Debrief(DAY, "A quiet day", "Nothing traded", (), ()), _Events(), later, CALENDAR, "ui"
    )
    assert get_manager_day(DAY, CALENDAR, later).debrief
    assert get_manager_day(date(2026, 9, 18), CALENDAR, later).plan is None
