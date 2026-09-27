from datetime import UTC, datetime, time, timedelta

import pytest

from openticker.core.scripts.models import (
    LOG_LIMIT_BYTES,
    ScriptCommandKind,
    ScriptCommandStatus,
    ScriptLimits,
    ScriptRun,
    ScriptRunStatus,
    ScriptSchedule,
    ScriptStopReason,
)
from openticker.events.types import ScriptExited, ScriptStarted
from openticker.storage import script_files
from openticker.storage.sqlite import scripts_repo
from openticker.storage.sqlite.api_keys_repo import list_api_keys
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.api_keys import authenticate, create_script_key
from openticker.use_cases.scripts import manage
from openticker.use_cases.scripts.supervise import (
    KEPT_LOGS,
    STOP_GRACE,
    SupervisorContext,
    process_script_commands,
    recover_scripts,
    start_scheduled_scripts,
    stop_all_scripts,
    watch_scripts,
)
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.fake_processes import FakeProcesses

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)  # Tuesday 09:30 IST
LIMITS = ScriptLimits(memory_mb=256, cpu_seconds=60)
BASE_URL = "http://127.0.0.1:8750"


class Recorded:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture
def processes() -> FakeProcesses:
    return FakeProcesses()


@pytest.fixture
def events() -> Recorded:
    return Recorded()


@pytest.fixture
def context(processes: FakeProcesses, events: Recorded) -> SupervisorContext:
    return SupervisorContext(processes, events, NO_HOLIDAYS, LIMITS, BASE_URL)


def _script(name: str = "bot") -> str:
    return manage.upload_script(name, "print('hi')\n", NOW).id


def _started(context: SupervisorContext, script_id: str, now: datetime = NOW) -> ScriptRun:
    manage.request_start(script_id, "mcp", now)
    process_script_commands(context, now)
    run = scripts_repo.recent_runs(script_id, 1)[0]
    assert run.status is ScriptRunStatus.RUNNING
    return run


def _run(run_id: str) -> ScriptRun:
    run = scripts_repo.find_run(run_id)
    assert run is not None
    return run


def _active_script_keys() -> set[str]:
    return {k.name for k in list_api_keys() if k.revoked_at is None and k.scope != "full"}


def test_a_start_runs_the_script_with_a_key_of_its_own(
    context: SupervisorContext, processes: FakeProcesses, events: Recorded
) -> None:
    script_id = _script()
    command = manage.request_start(script_id, "mcp", NOW)

    process_script_commands(context, NOW)

    run = scripts_repo.recent_runs(script_id, 1)[0]
    (launch,) = processes.launches
    assert run.pid in processes.running
    assert run.trigger == "mcp"
    assert launch.path == script_files.script_path(script_id)
    assert launch.log_path == script_files.log_path(script_id, run.id)
    assert (launch.base_url, launch.cpu_seconds) == (BASE_URL, 60)
    key = authenticate(launch.api_key)
    assert key is not None
    assert (key.name, key.scope) == (f"script-{run.id}", f"script:{script_id}")
    (done,) = manage.get_script(script_id, 5, False).commands
    assert (done.id, done.status, done.outcome) == (
        command.id,
        ScriptCommandStatus.DONE,
        f"started run {run.id}",
    )
    (started,) = events.events
    assert isinstance(started, ScriptStarted)
    assert (started.script_id, started.run_id, started.name, started.triggered_by) == (
        script_id,
        run.id,
        "bot",
        "mcp",
    )
    header = script_files.tail_log(script_id, run.id, 5)[0]
    assert header == [f"=== run {run.id} started 2026-09-22 09:30:00 IST by mcp ==="]


def test_a_run_that_exits_is_recorded_and_its_key_revoked(
    context: SupervisorContext, processes: FakeProcesses, events: Recorded
) -> None:
    script_id = _script()
    run = _started(context, script_id)
    assert run.pid is not None
    key = processes.launches[0].api_key

    watch_scripts(context, NOW)
    assert _run(run.id).status is ScriptRunStatus.RUNNING
    processes.exit(run.pid, 0)
    later = NOW + timedelta(minutes=5)
    watch_scripts(context, later)

    ended = _run(run.id)
    assert (ended.status, ended.stop_reason, ended.exit_code) == (
        ScriptRunStatus.ENDED,
        ScriptStopReason.EXITED,
        0,
    )
    assert ended.ended_at == later
    assert authenticate(key) is None
    exited = events.events[-1]
    assert isinstance(exited, ScriptExited)
    assert (exited.reason, exited.detail) == ("exited", "exited with code 0")
    assert script_files.tail_log(script_id, run.id, 1)[0] == [
        f"=== run {run.id} ended: exited, exited with code 0 ==="
    ]


def test_a_failed_run_says_how(context: SupervisorContext, processes: FakeProcesses) -> None:
    run = _started(context, _script())
    assert run.pid is not None
    processes.exit(run.pid, 1)

    watch_scripts(context, NOW)

    assert (_run(run.id).stop_reason, _run(run.id).stop_detail) == (
        ScriptStopReason.FAILED,
        "exited with code 1",
    )


def test_stop_asks_first_and_kills_what_outstays_the_grace(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    script_id = _script()
    run = _started(context, script_id)
    assert run.pid is not None
    processes.exit_on_signal = False

    manage.request_stop(script_id, "rest:ops", NOW)
    process_script_commands(context, NOW)
    assert processes.signals == [(run.pid, False)]
    assert _run(run.id).status is ScriptRunStatus.STOPPING
    watch_scripts(context, NOW + STOP_GRACE - timedelta(seconds=1))
    assert processes.signals == [(run.pid, False)]
    watch_scripts(context, NOW + STOP_GRACE)
    assert processes.signals[-1] == (run.pid, True)
    watch_scripts(context, NOW + STOP_GRACE)

    ended = _run(run.id)
    assert ended.stop_reason is ScriptStopReason.STOPPED
    assert ended.stop_detail == "stopped by rest:ops; killed by SIGKILL"
    assert ended.exit_code == -9
    (stop, _) = manage.get_script(script_id, 5, False).commands
    assert stop.outcome == f"stopping run {run.id}"


def test_a_stop_for_a_script_that_already_ended_changes_nothing(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    script_id = _script()
    run = _started(context, script_id)
    assert run.pid is not None
    manage.request_stop(script_id, "mcp", NOW)
    processes.exit(run.pid, 0)
    watch_scripts(context, NOW)

    process_script_commands(context, NOW)

    assert processes.signals == []
    assert manage.get_script(script_id, 5, False).commands[0].outcome == "was not running"


def test_a_script_over_its_memory_limit_is_killed_at_once(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    run = _started(context, _script())
    assert run.pid is not None
    processes.memory[run.pid] = 256 * 1024
    watch_scripts(context, NOW)
    assert processes.signals == []

    processes.memory[run.pid] = 256 * 1024 + 1
    watch_scripts(context, NOW)
    watch_scripts(context, NOW)

    assert processes.signals == [(run.pid, True)]
    assert _run(run.id).stop_reason is ScriptStopReason.MEMORY_LIMIT
    assert _run(run.id).stop_detail == "used 256 MB, over its 256 MB limit; killed by SIGKILL"


def test_a_runs_peak_memory_is_kept_when_it_grows_by_a_megabyte(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    run = _started(context, _script())
    assert run.pid is not None and run.peak_memory_kb is None
    for kb in (80_000, 80_500, 90_000, 40_000):
        processes.memory[run.pid] = kb
        watch_scripts(context, NOW)
        if kb == 80_500:
            assert _run(run.id).peak_memory_kb == 80_000  # under a megabyte more: not written

    assert _run(run.id).peak_memory_kb == 90_000


def test_a_script_that_prints_too_much_is_stopped(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    script_id = _script()
    run = _started(context, script_id)
    assert run.pid is not None
    with script_files.log_path(script_id, run.id).open("r+b") as log:
        log.truncate(LOG_LIMIT_BYTES)
    watch_scripts(context, NOW)
    assert processes.signals == []

    with script_files.log_path(script_id, run.id).open("r+b") as log:
        log.truncate(LOG_LIMIT_BYTES + 1)
    watch_scripts(context, NOW)
    watch_scripts(context, NOW)

    assert processes.signals == [(run.pid, False)]
    assert _run(run.id).stop_reason is ScriptStopReason.LOG_LIMIT
    assert "over the 50 MB a run may" in (_run(run.id).stop_detail or "")


def test_stop_time_stops_a_run_whoever_started_it(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    script_id = _script()
    run = _started(context, script_id)
    manage.schedule_script(script_id, ScriptSchedule(time(9, 15), stop_time=time(15, 0)))
    at_stop = datetime(2026, 9, 22, 9, 30, tzinfo=UTC)  # 15:00 IST

    watch_scripts(context, at_stop - timedelta(seconds=1))
    assert processes.signals == []
    watch_scripts(context, at_stop)
    watch_scripts(context, at_stop)

    assert _run(run.id).stop_reason is ScriptStopReason.SCHEDULE
    assert (_run(run.id).stop_detail or "").startswith("its stop_time 15:00")


def test_a_scheduled_script_starts_once_a_day_inside_its_window(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    script_id = _script()
    manage.schedule_script(script_id, ScriptSchedule(time(9, 15), stop_time=time(15, 0)))

    start_scheduled_scripts(context, NOW - timedelta(minutes=16))  # 09:14
    assert processes.launches == []
    start_scheduled_scripts(context, NOW)
    start_scheduled_scripts(context, NOW)
    (run,) = scripts_repo.recent_runs(script_id, 5)
    assert run.trigger == "schedule"
    assert run.pid is not None

    processes.exit(run.pid, 0)
    watch_scripts(context, NOW)
    start_scheduled_scripts(context, NOW + timedelta(hours=1))
    assert len(processes.launches) == 1  # that was the day's run

    wednesday = NOW + timedelta(days=1)
    start_scheduled_scripts(context, wednesday)
    assert len(processes.launches) == 2


def test_a_run_the_daemons_absence_ended_doesnt_count_as_the_days(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    script_id = _script()
    manage.schedule_script(script_id, ScriptSchedule(time(9, 15)))
    start_scheduled_scripts(context, NOW)
    stop_all_scripts(context, lambda: NOW, sleep=lambda _: None)

    start_scheduled_scripts(context, NOW + timedelta(minutes=2))

    reasons = [run.stop_reason for run in scripts_repo.recent_runs(script_id, 5)]
    assert reasons == [None, ScriptStopReason.DAEMON_STOPPED]


def test_a_run_by_hand_before_start_time_doesnt_take_the_days_run(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    script_id = _script()
    early = NOW - timedelta(minutes=30)  # 09:00
    run = _started(context, script_id, early)
    assert run.pid is not None
    processes.exit(run.pid, 0)
    watch_scripts(context, early)
    manage.schedule_script(script_id, ScriptSchedule(time(9, 15)))

    start_scheduled_scripts(context, NOW)

    assert len(processes.launches) == 2
    stopped = scripts_repo.recent_runs(script_id, 1)[0]
    manage.request_stop(script_id, "mcp", NOW)
    process_script_commands(context, NOW)
    watch_scripts(context, NOW)
    assert _run(stopped.id).stop_reason is ScriptStopReason.STOPPED
    start_scheduled_scripts(context, NOW + timedelta(minutes=1))
    assert len(processes.launches) == 2  # stopped by hand: not again today


def test_a_script_that_cant_start_is_recorded_and_not_retried(
    context: SupervisorContext, processes: FakeProcesses, events: Recorded
) -> None:
    script_id = _script()
    manage.schedule_script(script_id, ScriptSchedule(time(9, 15)))
    processes.unsupported = True
    command = manage.request_start(script_id, "mcp", NOW)

    process_script_commands(context, NOW)
    start_scheduled_scripts(context, NOW)

    (run,) = scripts_repo.recent_runs(script_id, 5)
    assert run.stop_reason is ScriptStopReason.START_FAILED
    assert run.stop_detail == "could not start: scripts run only on Linux and macOS"
    (refused,) = manage.get_script(script_id, 5, False).commands
    assert (refused.id, refused.status) == (command.id, ScriptCommandStatus.REFUSED)
    assert refused.outcome == run.stop_detail
    assert _active_script_keys() == set()
    assert [type(e) for e in events.events] == [ScriptExited]


def test_a_start_for_a_running_or_deleted_script_is_refused(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    script_id = _script()
    run = _started(context, script_id)
    with write_transaction() as session:
        late = scripts_repo.add_command(session, script_id, ScriptCommandKind.START, "mcp", NOW)
    process_script_commands(context, NOW)
    assert manage.get_script(script_id, 5, False).commands[0].outcome == (
        f"already running (run {run.id})"
    )

    with write_transaction() as session:
        scripts_repo.delete_script(session, script_id)
        orphan = scripts_repo.add_command(session, script_id, ScriptCommandKind.START, "mcp", NOW)
    process_script_commands(context, NOW)
    assert len(processes.launches) == 1
    assert scripts_repo.next_pending_command() is None
    assert late.id != orphan.id


def test_recovery_watches_scripts_still_running_and_ends_the_rest(
    context: SupervisorContext, processes: FakeProcesses, events: Recorded
) -> None:
    alive = _started(context, _script("alive"))
    by_hand = _started(context, _script("by-hand"))
    scheduled_id = _script("scheduled")
    manage.schedule_script(scheduled_id, ScriptSchedule(time(9, 15)))
    start_scheduled_scripts(context, NOW)
    scheduled = scripts_repo.recent_runs(scheduled_id, 1)[0]
    unrecorded_id = _script("unrecorded")
    with write_transaction() as session:  # died between writing the run and its pid
        unrecorded = scripts_repo.add_run(session, unrecorded_id, "schedule", NOW)
    assert by_hand.pid is not None and scheduled.pid is not None
    processes.exit(by_hand.pid, None)
    processes.exit(scheduled.pid, None)
    processes.running[9999] = script_files.script_path(unrecorded_id)
    stale_key = create_script_key("scr_old", "srn_old", NOW)

    # A new daemon: nothing of the old one's but the database and the processes.
    fresh = FakeProcesses()
    fresh.running = dict(processes.running)
    later = NOW + timedelta(minutes=3)
    count = recover_scripts(SupervisorContext(fresh, events, NO_HOLIDAYS, LIMITS, BASE_URL), later)

    assert count == 1
    assert fresh.adopted == {alive.pid}
    assert _run(alive.id).status is ScriptRunStatus.RUNNING
    assert fresh.signals == [(9999, True)]
    for gone in (by_hand, scheduled, unrecorded):
        assert _run(gone.id).stop_reason is ScriptStopReason.LOST
    # Started by hand: started again. Scheduled: left to its schedule.
    (restarted,) = fresh.launches
    assert restarted.script_id == by_hand.script_id
    assert scripts_repo.recent_runs(by_hand.script_id, 1)[0].trigger == "recovery"
    assert authenticate(stale_key) is None
    assert _active_script_keys() == {
        f"script-{alive.id}",
        f"script-{scripts_repo.recent_runs(by_hand.script_id, 1)[0].id}",
    }


def test_recovery_finishes_a_stop_the_last_daemon_had_asked_for(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    script_id = _script()
    run = _started(context, script_id)
    assert run.pid is not None
    processes.exit_on_signal = False
    manage.request_stop(script_id, "mcp", NOW)
    process_script_commands(context, NOW)
    processes.exit(run.pid, None)

    fresh = FakeProcesses()
    recover_scripts(SupervisorContext(fresh, Recorded(), NO_HOLIDAYS, LIMITS, BASE_URL), NOW)

    assert _run(run.id).stop_reason is ScriptStopReason.STOPPED
    assert fresh.launches == []


def test_shutdown_stops_every_script_and_kills_what_wont(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    polite = _started(context, _script("polite"))
    stuck = _started(context, _script("stuck"))
    assert polite.pid is not None and stuck.pid is not None
    processes.exit_on_signal = False
    processes.exit(polite.pid, 0)  # exits as the signal arrives
    moments = iter(NOW + timedelta(seconds=n) for n in range(100))

    stop_all_scripts(context, lambda: next(moments), sleep=lambda _: None)

    assert (stuck.pid, True) in processes.signals
    for run in (polite, stuck):
        assert _run(run.id).stop_reason is ScriptStopReason.DAEMON_STOPPED
    assert _run(polite.id).stop_detail == "openticker-serve shut down; exited with code 0"
    assert _run(stuck.id).exit_code == -9
    assert _active_script_keys() == set()


def test_only_the_latest_runs_logs_are_kept(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    script_id = _script()
    ids = []
    for n in range(KEPT_LOGS + 2):
        run = _started(context, script_id, NOW + timedelta(minutes=n))
        assert run.pid is not None
        processes.exit(run.pid, 0)
        watch_scripts(context, NOW + timedelta(minutes=n))
        ids.append(run.id)

    kept = {path.stem for path in (script_files.script_dir(script_id) / "logs").glob("*.log")}
    assert kept == set(ids[-KEPT_LOGS:])


def test_shutdown_gives_up_on_a_process_not_even_sigkill_ends(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    run = _started(context, _script())
    processes.unkillable = True
    moments = iter(NOW + timedelta(seconds=n) for n in range(100))

    stop_all_scripts(context, lambda: next(moments), sleep=lambda _: None)

    assert processes.signals == [(run.pid, False), (run.pid, True)]
    ended = _run(run.id)
    assert (ended.stop_reason, ended.exit_code) == (ScriptStopReason.DAEMON_STOPPED, None)


def test_a_running_scheduled_script_is_not_started_twice(
    context: SupervisorContext, processes: FakeProcesses
) -> None:
    script_id = _script()
    manage.schedule_script(script_id, ScriptSchedule(time(9, 15)))

    for seconds in range(3):
        start_scheduled_scripts(context, NOW + timedelta(seconds=seconds))

    assert len(processes.launches) == 1
    assert len(scripts_repo.recent_runs(script_id, 5)) == 1
