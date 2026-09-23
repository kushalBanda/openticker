import pytest

from openticker.adapters.inbound.daemon.main import (
    BindConfigError,
    _log_config,
    is_loopback,
    parse_bind,
    run,
)
from openticker.use_cases.api_keys import authenticate


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
