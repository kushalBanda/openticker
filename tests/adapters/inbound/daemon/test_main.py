import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from openticker.adapters.inbound.daemon.main import (
    BindConfigError,
    _log_config,
    is_loopback,
    open_when_up,
    parse_bind,
    run,
    web_settings,
)
from openticker.use_cases.api_keys import authenticate
from openticker.use_cases.web_sessions import redeem_sign_in_link


def _redeems(link: str) -> bool:
    token = parse_qs(urlsplit(link).query)["token"][0]
    from datetime import UTC, datetime

    return redeem_sign_in_link(token, None, datetime.now(UTC)) is not None


def test_bind_defaults_to_this_machine_only() -> None:
    assert parse_bind({}) == ("127.0.0.1", 8750)
    assert parse_bind({"OPENTICKER_BIND": "0.0.0.0:9000"}) == ("0.0.0.0", 9000)
    assert parse_bind({"OPENTICKER_BIND": "[::1]:9000"}) == ("::1", 9000)
    for bad in ("8750", "localhost:", "localhost:http", "localhost:70000"):
        with pytest.raises(BindConfigError, match="OPENTICKER_BIND"):
            parse_bind({"OPENTICKER_BIND": bad})


def test_loopback_detection() -> None:
    assert is_loopback("127.0.0.1") and is_loopback("localhost") and is_loopback("::1")
    assert not is_loopback("0.0.0.0") and not is_loopback("192.168.1.5")


def test_keys_commands_print_a_key_once_and_list_without_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as created:
        run(["keys", "create", "laptop"])
    key = capsys.readouterr().out.strip()

    with pytest.raises(SystemExit) as listed:
        run(["keys", "list"])
    listing = capsys.readouterr().out

    assert created.value.code == 0 and listed.value.code == 0
    assert authenticate(key) is not None
    assert "laptop" in listing and "active" in listing and key not in listing

    with pytest.raises(SystemExit) as revoked:
        run(["keys", "revoke", "laptop"])
    assert revoked.value.code == 0 and authenticate(key) is None


def test_keys_commands_fail_with_a_message(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as revoked:
        run(["keys", "revoke", "nobody"])

    assert revoked.value.code == 1
    assert "no active API key named 'nobody'" in capsys.readouterr().err


def test_every_log_handler_hides_alert_tokens() -> None:
    config = _log_config()

    assert config["handlers"] and all(
        "hide_alert_tokens" in handler["filters"] for handler in config["handlers"].values()
    )


def test_scripts_reach_the_server_through_this_machine() -> None:
    from openticker.adapters.inbound.daemon.main import local_url

    assert local_url("127.0.0.1", 8750) == "http://127.0.0.1:8750"
    assert local_url("0.0.0.0", 9000) == "http://127.0.0.1:9000"
    assert local_url("::", 9000) == "http://[::1]:9000"
    assert local_url("::1", 9000) == "http://[::1]:9000"
    assert local_url("192.168.1.5", 80) == "http://192.168.1.5:80"


def test_sigterm_exits_through_the_shutdown_path() -> None:
    import signal

    from openticker.adapters.inbound.daemon.main import exit_on_signal

    with pytest.raises(SystemExit) as exited:
        exit_on_signal(signal.SIGTERM, None)
    assert exited.value.code == 143


def test_sigterm_stops_the_server_through_its_shutdown_path(tmp_path: Path) -> None:
    """uvicorn raises SIGTERM again after its own shutdown; the server must
    still leave through the code that stops its loops and scripts."""
    import signal
    import socket
    import subprocess
    import sys
    import time

    import httpx

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "OPENTICKER_HOME": str(tmp_path),
        "OPENTICKER_BIND": f"127.0.0.1:{port}",
    }
    server = subprocess.Popen(
        [sys.executable, "-c", "from openticker.adapters.inbound.daemon.main import run; run([])"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health").is_success:
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        server.send_signal(signal.SIGTERM)
        assert server.wait(timeout=20) == 128 + signal.SIGTERM  # not killed by it: -15
        assert server.stdout is not None
        assert f"http://127.0.0.1:{port}/login?token=" in server.stdout.read()
    finally:
        server.kill()


def test_ui_login_prints_a_new_link(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as done:
        run(["ui", "login"])
    link = capsys.readouterr().out.strip()

    assert done.value.code == 0
    assert link.startswith("http://127.0.0.1:8750/login?token=")
    assert _redeems(link)


def test_ui_login_in_dev_points_at_the_vite_server(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        run(["--dev", "ui", "login"])

    assert capsys.readouterr().out.startswith("http://localhost:5173/login?token=")


def test_dev_flag_allows_vite_origin() -> None:
    assert web_settings("127.0.0.1", 8750, dev=False, env={}).dev_origin is None
    dev = web_settings("127.0.0.1", 8750, dev=True, env={})
    assert (dev.own_origin, dev.port, dev.dev_origin) == (
        "http://127.0.0.1:8750",
        8750,
        "http://localhost:5173",
    )
    other = {"OPENTICKER_UI_ORIGIN": "http://localhost:3000"}
    assert (
        web_settings("127.0.0.1", 8750, dev=True, env=other).dev_origin == "http://localhost:3000"
    )


def test_browser_opens_the_link_once_the_server_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    import httpx

    calls = iter(range(2))

    def get(url: str, timeout: float) -> httpx.Response:
        if next(calls) == 0:
            raise httpx.ConnectError("not yet")
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "get", get)
    opened: list[str] = []

    open_when_up("http://x/login?token=t", "http://x/health", threading.Event(), opened.append)

    assert opened == ["http://x/login?token=t"]


def test_browser_stays_closed_when_the_server_stops_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    import httpx

    def get(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", get)
    stop = threading.Event()
    stop.set()
    opened: list[str] = []

    open_when_up("http://x/login?token=t", "http://x/health", stop, opened.append)

    assert opened == []
