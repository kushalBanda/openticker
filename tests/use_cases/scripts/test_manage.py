from datetime import UTC, datetime, time

import pytest

from openticker.core.scripts.models import (
    MAX_SCRIPT_BYTES,
    InvalidScriptError,
    ScriptCommandKind,
    ScriptCommandStatus,
    ScriptSchedule,
    ScriptStopReason,
)
from openticker.storage import script_files
from openticker.storage.sqlite import scripts_repo
from openticker.storage.sqlite.scripts_repo import DuplicateScriptNameError
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.scripts import manage
from openticker.use_cases.scripts.manage import (
    ScriptRunningError,
    ScriptStateError,
    UnknownScriptError,
)

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)  # Tuesday 09:30 IST
SOURCE = "print('hello')\n"


def _running(script_id: str) -> str:
    """A run the daemon would have started; its id."""
    with write_transaction() as session:
        run = scripts_repo.add_run(session, script_id, "mcp", NOW)
        scripts_repo.set_pid(session, run.id, 4242)
    return run.id


def test_upload_keeps_the_source_as_a_file_and_its_digest_in_the_database() -> None:
    stored = manage.upload_script("momentum", SOURCE, NOW)

    assert stored.id.startswith("scr_")
    assert script_files.read_source(stored.id) == SOURCE
    assert script_files.script_path(stored.id).name == "main.py"
    assert stored.source_bytes == len(SOURCE)
    assert len(stored.source_sha256) == 64
    assert stored.schedule is None
    assert [s.script.name for s in manage.list_scripts()] == ["momentum"]


@pytest.mark.parametrize(
    ("name", "source", "why"),
    [
        (" padded", SOURCE, "script name ' padded' must be"),
        ("x" * 61, SOURCE, "must be 1-60 letters"),
        ("ok", "def broken(:\n", "not valid Python: .* \\(line 1\\)"),
        ("ok", "print('a')\x00", "not valid Python"),
        ("ok", "#" * (MAX_SCRIPT_BYTES + 1), "the most is 262,144"),
    ],
)
def test_upload_refuses_a_bad_name_or_a_file_that_isnt_python(
    name: str, source: str, why: str
) -> None:
    with pytest.raises(InvalidScriptError, match=why):
        manage.upload_script(name, source, NOW)
    assert manage.list_scripts() == []


def test_parsing_a_script_runs_none_of_it(tmp_path_factory: pytest.TempPathFactory) -> None:
    marker = tmp_path_factory.mktemp("marker") / "ran"
    manage.upload_script("inert", f"open({str(marker)!r}, 'w').write('x')\n", NOW)
    assert not marker.exists()


def test_names_are_unique_and_a_script_can_keep_its_own() -> None:
    first = manage.upload_script("alpha", SOURCE, NOW)
    manage.upload_script("beta", SOURCE, NOW)

    with pytest.raises(DuplicateScriptNameError, match="'alpha' already exists"):
        manage.upload_script("alpha", SOURCE, NOW)
    with pytest.raises(DuplicateScriptNameError, match="'beta' already exists"):
        manage.update_script(first.id, "beta", SOURCE, NOW)
    updated = manage.update_script(first.id, "alpha", "print(2)\n", NOW)
    assert updated.source_sha256 != first.source_sha256
    assert script_files.read_source(first.id) == "print(2)\n"


def test_a_running_script_or_one_about_to_start_cant_be_changed_or_deleted() -> None:
    stored = manage.upload_script("busy", SOURCE, NOW)
    manage.request_start(stored.id, "mcp", NOW)

    with pytest.raises(ScriptRunningError, match="stop_script it before changing it"):
        manage.update_script(stored.id, "busy", "print(2)\n", NOW)
    with pytest.raises(ScriptRunningError, match="before deleting it"):
        manage.delete_script(stored.id)
    assert script_files.read_source(stored.id) == SOURCE

    manage.request_stop(stored.id, "mcp", NOW)  # cancels the start
    _running(stored.id)
    with pytest.raises(ScriptRunningError):
        manage.delete_script(stored.id)


def test_delete_removes_the_script_its_runs_and_its_files() -> None:
    stored = manage.upload_script("gone", SOURCE, NOW)
    run_id = _running(stored.id)
    script_files.append_log(stored.id, run_id, "output")
    with write_transaction() as session:
        scripts_repo.end_run(session, run_id, ScriptStopReason.EXITED, "done", 0, NOW)

    manage.delete_script(stored.id)

    assert not script_files.script_dir(stored.id).exists()
    assert scripts_repo.find_run(run_id) is None
    with pytest.raises(UnknownScriptError, match="list_scripts shows them"):
        manage.get_script(stored.id, 10, False)


def test_start_is_a_command_refused_while_running_or_already_asked_for() -> None:
    stored = manage.upload_script("go", SOURCE, NOW)

    command = manage.request_start(stored.id, "rest:ops", NOW)

    assert command.kind is ScriptCommandKind.START
    assert command.status is ScriptCommandStatus.PENDING
    assert command.triggered_by == "rest:ops"
    with pytest.raises(ScriptStateError, match="already being started"):
        manage.request_start(stored.id, "mcp", NOW)
    with write_transaction() as session:
        scripts_repo.settle_command(session, command.id, ScriptCommandStatus.DONE, "ok", NOW)
    run_id = _running(stored.id)
    with pytest.raises(ScriptStateError, match=f"already running \\(run {run_id}\\)"):
        manage.request_start(stored.id, "mcp", NOW)
    with pytest.raises(UnknownScriptError):
        manage.request_start("scr_missing", "mcp", NOW)


def test_stop_cancels_a_pending_start_and_is_refused_when_nothing_runs() -> None:
    stored = manage.upload_script("halt", SOURCE, NOW)
    with pytest.raises(ScriptStateError, match="'halt' is not running; nothing to stop"):
        manage.request_stop(stored.id, "mcp", NOW)

    start = manage.request_start(stored.id, "mcp", NOW)
    stop = manage.request_stop(stored.id, "mcp", NOW)

    commands = {c.id: c for c in manage.get_script(stored.id, 10, False).commands}
    assert commands[start.id].status is ScriptCommandStatus.REFUSED
    assert commands[start.id].outcome == "cancelled by a stop"
    assert commands[stop.id].kind is ScriptCommandKind.STOP
    assert commands[stop.id].status is ScriptCommandStatus.PENDING


def test_a_schedule_is_stored_and_removed() -> None:
    stored = manage.upload_script("daily", SOURCE, NOW)
    schedule = ScriptSchedule(start_time=time(9, 20), stop_time=time(15, 0))

    assert manage.schedule_script(stored.id, schedule).schedule == schedule
    assert manage.get_script(stored.id, 1, False).script.schedule == schedule
    assert manage.unschedule_script(stored.id).schedule is None
    with pytest.raises(UnknownScriptError):
        manage.schedule_script("scr_missing", schedule)


def test_get_script_returns_the_source_only_when_asked() -> None:
    stored = manage.upload_script("peek", SOURCE, NOW)

    assert manage.get_script(stored.id, 5, False).source is None
    assert manage.get_script(stored.id, 5, True).source == SOURCE


def test_logs_are_the_latest_runs_last_lines_unless_a_run_is_named() -> None:
    stored = manage.upload_script("chatty", SOURCE, NOW)
    with pytest.raises(ScriptStateError, match="has never run"):
        manage.get_logs(stored.id, None, 10)
    first = _running(stored.id)
    for n in range(5):
        script_files.append_log(stored.id, first, f"first {n}")
    with write_transaction() as session:
        scripts_repo.end_run(session, first, ScriptStopReason.EXITED, "done", 0, NOW)
    later = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)
    with write_transaction() as session:
        second = scripts_repo.add_run(session, stored.id, "mcp", later).id
    script_files.append_log(stored.id, second, "second")

    latest = manage.get_logs(stored.id, None, 10)
    assert latest.run.id == second
    assert latest.lines == ["second"]
    named = manage.get_logs(stored.id, first, 2)
    assert named.lines == ["first 3", "first 4"]
    assert named.truncated
    assert not manage.get_logs(stored.id, first, 5).truncated
    with pytest.raises(UnknownScriptError, match="has no run 'srn_other'"):
        manage.get_logs(stored.id, "srn_other", 10)


def test_a_long_log_is_read_from_its_end() -> None:
    stored = manage.upload_script("verbose", SOURCE, NOW)
    run_id = _running(stored.id)
    path = script_files.log_path(stored.id, run_id)
    path.write_text("".join(f"line {n:07d}\n" for n in range(40_000)))

    found = manage.get_logs(stored.id, run_id, 3)

    assert found.lines == ["line 0039997", "line 0039998", "line 0039999"]
    assert found.truncated


def test_logs_name_only_this_scripts_runs_and_at_most_a_thousand_lines() -> None:
    mine = manage.upload_script("mine", SOURCE, NOW)
    other = manage.upload_script("other", SOURCE, NOW)
    theirs = _running(other.id)
    run_id = _running(mine.id)
    path = script_files.log_path(mine.id, run_id)
    path.write_text("".join(f"{n}\n" for n in range(1500)))

    with pytest.raises(UnknownScriptError, match=f"'mine' has no run '{theirs}'"):
        manage.get_logs(mine.id, theirs, 10)
    found = manage.get_logs(mine.id, run_id, 5000)
    assert len(found.lines) == manage.MAX_LOG_LINES
    assert found.lines[-1] == "1499"
