"""The supervisor against real child processes (POSIX only)."""

import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from openticker.adapters.scripts.supervisor import ProcessSupervisor, script_env
from openticker.ports.script_process_port import (
    Exited,
    ScriptHostingUnsupportedError,
    ScriptLaunch,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="scripts run only on POSIX")

KEY = "otk_script-key-for-tests"


def _launch(tmp_path: Path, source: str, cpu_seconds: int = 60) -> ScriptLaunch:
    home = tmp_path / "scr_test"
    home.mkdir(exist_ok=True)
    path = home / "main.py"
    path.write_text(source)
    return ScriptLaunch(
        script_id="scr_test",
        path=path,
        log_path=home / "run.log",
        api_key=KEY,
        base_url="http://127.0.0.1:8750",
        cpu_seconds=cpu_seconds,
    )


def _wait(supervisor: ProcessSupervisor, pid: int, seconds: float = 15) -> Exited:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        exited = supervisor.poll(pid)
        if exited is not None:
            return exited
        time.sleep(0.05)
    supervisor.stop(pid, force=True)
    raise AssertionError(f"process {pid} still running after {seconds}s")


def _wait_for(path: Path, text: str, seconds: float = 15) -> str:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = path.read_text() if path.exists() else ""
        if text in found:
            return found
        time.sleep(0.05)
    raise AssertionError(f"{text!r} never appeared in {path}")


def test_script_env_has_no_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "KITE_API_KEY": "kite-key-value",
        "KITE_API_SECRET": "kite-secret-value",
        "SMTP_PASSWORD": "smtp-password-value",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.test/secret-path",
        "OPENTICKER_CREDENTIALS_KEY": "fernet-key-value",
    }.items():
        monkeypatch.setenv(name, value)
    launch = _launch(
        tmp_path,
        "import json, os\nprint(json.dumps({'env': dict(os.environ), 'cwd': os.getcwd()}))\n",
    )
    supervisor = ProcessSupervisor()

    assert _wait(supervisor, supervisor.start(launch)) == Exited(0)

    seen = json.loads(launch.log_path.read_text())
    assert set(seen["env"]) - {"__CF_USER_TEXT_ENCODING"} == {
        "PATH",
        "HOME",
        "LANG",
        "PYTHONUNBUFFERED",
        "OPENTICKER_URL",
        "OPENTICKER_API_KEY",
        "OPENTICKER_SCRIPT_ID",
    }
    assert seen["env"]["OPENTICKER_API_KEY"] == KEY
    assert seen["env"]["OPENTICKER_SCRIPT_ID"] == "scr_test"
    assert seen["env"]["OPENTICKER_URL"] == "http://127.0.0.1:8750"
    assert Path(seen["env"]["HOME"]).resolve() == launch.path.parent.resolve()
    assert Path(seen["cwd"]).resolve() == launch.path.parent.resolve()
    log = launch.log_path.read_text()
    for secret in ("kite-", "smtp-password", "secret-path", "fernet-key", "OPENTICKER_HOME"):
        assert secret not in log


def test_script_env_is_built_from_nothing_but_path_and_lang() -> None:
    parent = {"PATH": "/opt/bin", "LANG": "en_IN.UTF-8", "KITE_API_SECRET": "x", "HOME": "/root"}

    env = script_env("scr_a", "otk_k", "http://h:1", Path("/data/scripts/scr_a"), parent)

    assert env == {
        "PATH": "/opt/bin",
        "HOME": "/data/scripts/scr_a",
        "LANG": "en_IN.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "OPENTICKER_URL": "http://h:1",
        "OPENTICKER_API_KEY": "otk_k",
        "OPENTICKER_SCRIPT_ID": "scr_a",
    }
    bare = script_env("scr_a", "otk_k", "http://h:1", Path("/x"), {})
    assert (bare["PATH"], bare["LANG"]) == (os.defpath, "C.UTF-8")


def test_output_and_exit_code_are_kept(tmp_path: Path) -> None:
    launch = _launch(
        tmp_path, "import sys\nprint('out')\nprint('err', file=sys.stderr)\nsys.exit(3)\n"
    )
    launch.log_path.write_text("=== header ===\n")
    supervisor = ProcessSupervisor()

    assert _wait(supervisor, supervisor.start(launch)) == Exited(3)
    assert launch.log_path.read_text().splitlines() == ["=== header ===", "out", "err"]


def test_cpu_time_is_limited(tmp_path: Path) -> None:
    launch = _launch(tmp_path, "while True:\n    pass\n", cpu_seconds=1)
    supervisor = ProcessSupervisor()

    assert _wait(supervisor, supervisor.start(launch)) == Exited(-signal.SIGXCPU)


def test_stop_reaches_what_the_script_started_too(tmp_path: Path) -> None:
    launch = _launch(
        tmp_path,
        "import subprocess, time\n"
        "child = subprocess.Popen(['sleep', '60'])\n"
        "print('child', child.pid, flush=True)\n"
        "time.sleep(60)\n",
    )
    supervisor = ProcessSupervisor()
    pid = supervisor.start(launch)
    child = int(_wait_for(launch.log_path, "child ").split()[1])

    assert supervisor.poll(pid) is None
    assert supervisor.memory_kb([pid])[pid] > 1000  # the script and its child together
    assert supervisor.memory_kb([]) == {}
    supervisor.stop(pid, force=False)

    assert _wait(supervisor, pid) == Exited(-signal.SIGTERM)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("the script's child outlived the stop")
    supervisor.stop(pid, force=True)  # already gone: no error


def test_a_new_supervisor_finds_and_adopts_a_running_script(tmp_path: Path) -> None:
    launch = _launch(tmp_path, "import time\nprint('up', flush=True)\ntime.sleep(60)\n")
    first = ProcessSupervisor()
    pid = first.start(launch)
    _wait_for(launch.log_path, "up")

    second = ProcessSupervisor()
    assert second.find(launch.path) == [pid]
    assert second.find(tmp_path / "other.py") == []
    assert not second.adopt(pid, tmp_path / "other.py")
    assert second.adopt(pid, launch.path)
    assert second.poll(pid) is None

    second.stop(pid, force=True)
    # Reaped by its parent, as init would once the old daemon is gone.
    assert _wait(first, pid) == Exited(-signal.SIGKILL)
    assert second.poll(pid) == Exited(None)  # not its child: the code is unknown
    assert not second.adopt(pid, launch.path)


def test_scripts_are_refused_where_they_cant_be_limited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launch = _launch(tmp_path, "print('never')\n")
    supervisor = ProcessSupervisor()
    monkeypatch.setattr("openticker.adapters.scripts.supervisor.os.name", "nt")

    with pytest.raises(ScriptHostingUnsupportedError, match="only on Linux and macOS"):
        supervisor.start(launch)
    assert not launch.log_path.exists()


def test_the_script_runs_under_this_python(tmp_path: Path) -> None:
    launch = _launch(tmp_path, "import sys\nprint(sys.executable)\n")
    supervisor = ProcessSupervisor()

    assert _wait(supervisor, supervisor.start(launch)) == Exited(0)
    assert launch.log_path.read_text().strip() == sys.executable


def test_memory_is_measured_even_when_the_system_compresses_it(tmp_path: Path) -> None:
    launch = _launch(
        tmp_path,
        "import os, time\n"
        "held = [os.urandom(10 * 1024 * 1024) for _ in range(15)]\n"
        "print('holding', flush=True)\n"
        "time.sleep(60)\n",
    )
    supervisor = ProcessSupervisor()
    pid = supervisor.start(launch)
    try:
        _wait_for(launch.log_path, "holding")
        assert supervisor.memory_kb([pid])[pid] > 140 * 1024
    finally:
        supervisor.stop(pid, force=True)
        _wait(supervisor, pid)


def test_memory_on_macos_is_the_footprint_and_elsewhere_the_resident_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openticker.adapters.scripts import supervisor as module

    if sys.platform == "darwin":
        footprint = module._footprint_kb(os.getpid())
        assert footprint is not None and footprint > 1000
    else:
        assert module._footprint_kb(os.getpid()) is None
    launch = _launch(tmp_path, "import time\nprint('up', flush=True)\ntime.sleep(60)\n")
    supervisor = ProcessSupervisor()
    pid = supervisor.start(launch)
    try:
        _wait_for(launch.log_path, "up")
        monkeypatch.setattr(module, "_footprint_kb", lambda pid: 7_000_000)
        assert supervisor.memory_kb([pid])[pid] == 7_000_000
        monkeypatch.setattr(module, "_footprint_kb", lambda pid: None)
        assert 1000 < supervisor.memory_kb([pid])[pid] < 7_000_000  # resident size
    finally:
        supervisor.stop(pid, force=True)
        _wait(supervisor, pid)
