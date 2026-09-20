import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "connect_adapter.py"
_spec = importlib.util.spec_from_file_location("connect_adapter_script", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
connect_adapter_script = importlib.util.module_from_spec(_spec)
sys.modules["connect_adapter_script"] = connect_adapter_script
_spec.loader.exec_module(connect_adapter_script)


@pytest.mark.asyncio
async def test_run_connects_and_saves_credentials(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(connect_adapter_script.webbrowser, "open", lambda _url: None)
    monkeypatch.setattr(connect_adapter_script.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(
        connect_adapter_script,
        "exchange_request_token",
        lambda api_key, api_secret, request_token: "stub-access-token",
    )
    saved: dict[str, object] = {}
    monkeypatch.setattr(
        connect_adapter_script,
        "save_credentials",
        lambda provider, creds: saved.update({"provider": provider, "creds": creds}),
    )
    monkeypatch.setattr(
        connect_adapter_script,
        "_kite_app_credentials",
        lambda: ("stub-key", "stub-secret"),
    )

    result = await connect_adapter_script._run("kite")

    assert result == {"provider": "kite", "status": "connected"}
    assert saved["provider"] == "kite"
    assert saved["creds"] == {"api_key": "stub-key", "access_token": "stub-access-token"}


async def _fake_to_thread(func, *args, **kwargs):  # type: ignore[no-untyped-def]
    return "stub-request-token"
