import threading
from datetime import UTC, datetime, time, timedelta

import pytest

from openticker.adapters.inbound.daemon.script_loop import ScriptLoop
from openticker.core.calendar.models import MarketCalendar
from openticker.core.scripts.models import (
    ScriptLimits,
    ScriptRunStatus,
    ScriptSchedule,
    ScriptStopReason,
)
from openticker.storage.sqlite import scripts_repo
from openticker.use_cases.scripts import manage
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.fake_processes import FakeProcesses

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)  # Tuesday 09:30 IST


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class Recorded:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def _loop(
    processes: FakeProcesses, clock: Clock, loads: list[datetime] | None = None
) -> ScriptLoop:
    def calendar() -> MarketCalendar:
        if loads is not None:
            loads.append(clock.now)
        return NO_HOLIDAYS

    return ScriptLoop(
        processes, Recorded(), calendar, ScriptLimits(), "http://127.0.0.1:8750", clock
    )


def test_a_pass_starts_what_was_asked_and_what_is_scheduled_then_records_exits() -> None:
    processes, clock = FakeProcesses(), Clock()
    loop = _loop(processes, clock)
    by_hand = manage.upload_script("by-hand", "pass\n", NOW).id
    scheduled = manage.upload_script("scheduled", "pass\n", NOW).id
    manage.schedule_script(scheduled, ScriptSchedule(time(9, 15)))
    manage.request_start(by_hand, "mcp", NOW)

    loop.step()

    runs = {s: scripts_repo.recent_runs(s, 1)[0] for s in (by_hand, scheduled)}
    assert {s: r.trigger for s, r in runs.items()} == {by_hand: "mcp", scheduled: "schedule"}
    for run in runs.values():
        assert run.pid is not None
        processes.exit(run.pid, 0)
    clock.now += timedelta(seconds=1)
    loop.step()
    assert all(
        scripts_repo.recent_runs(s, 1)[0].stop_reason is ScriptStopReason.EXITED for s in runs
    )
    assert len(processes.launches) == 2  # the scheduled one has had its day


def test_the_first_pass_takes_back_scripts_left_running() -> None:
    old = FakeProcesses()
    old_loop = _loop(old, Clock())
    script_id = manage.upload_script("long", "pass\n", NOW).id
    manage.request_start(script_id, "mcp", NOW)
    old_loop.step()
    run = scripts_repo.recent_runs(script_id, 1)[0]

    fresh = FakeProcesses()
    fresh.running = dict(old.running)
    _loop(fresh, Clock()).step()

    assert fresh.adopted == {run.pid}
    assert scripts_repo.recent_runs(script_id, 1)[0].status is ScriptRunStatus.RUNNING


def test_stopping_the_loop_stops_every_script() -> None:
    processes, clock = FakeProcesses(), Clock()
    loop = _loop(processes, clock)
    script_id = manage.upload_script("bot", "pass\n", NOW).id
    manage.request_start(script_id, "mcp", NOW)
    loop.step()
    stop = threading.Event()
    stop.set()

    loop.run(stop)

    run = scripts_repo.recent_runs(script_id, 1)[0]
    assert run.stop_reason is ScriptStopReason.DAEMON_STOPPED
    assert processes.signals == [(run.pid, False)]


def test_the_calendar_is_reloaded_every_ten_minutes() -> None:
    clock, loads = Clock(), list[datetime]()
    loop = _loop(FakeProcesses(), clock, loads)

    loop.step()
    clock.now += timedelta(minutes=9)
    loop.step()
    clock.now += timedelta(minutes=1)
    loop.step()

    assert loads == [NOW, NOW + timedelta(minutes=10)]


def test_a_failing_pass_is_logged_once_and_the_loop_goes_on(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    loop = _loop(FakeProcesses(), Clock())
    passes = []

    def failing() -> None:
        passes.append(1)
        if len(passes) == 3:
            stop.set()
        raise RuntimeError("database is locked")

    stop = threading.Event()
    monkeypatch.setattr(loop, "step", failing)
    monkeypatch.setattr(stop, "wait", lambda timeout: None)

    loop.run(stop)

    assert len(passes) == 3
    assert caplog.text.count("script supervisor pass failed") == 1
