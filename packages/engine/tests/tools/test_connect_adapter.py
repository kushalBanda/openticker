from unittest.mock import patch

import pytest
from engine.core.exceptions import EngineError
from engine.tools.connect_adapter import connect_adapter


@pytest.mark.asyncio
async def test_connect_adapter_rejects_unsupported_provider() -> None:
    with pytest.raises(EngineError, match="groww"):
        await connect_adapter(provider="groww")


@pytest.mark.asyncio
async def test_connect_adapter_runs_kite_flow_and_saves_credentials() -> None:
    with (
        patch("engine.tools.connect_adapter._kite_app_credentials", return_value=("k1", "s1")),
        patch("engine.tools.connect_adapter.webbrowser.open"),
        patch("engine.tools.connect_adapter._await_request_token", return_value="rt1"),
        patch("engine.tools.connect_adapter._exchange_for_access_token", return_value="at1"),
        patch("engine.tools.connect_adapter.save_credentials") as mock_save,
    ):
        result = await connect_adapter(provider="kite")

    mock_save.assert_called_once_with("kite", {"api_key": "k1", "access_token": "at1"})
    assert result == {"provider": "kite", "status": "connected"}


@pytest.mark.asyncio
async def test_connect_adapter_raises_engine_error_without_app_credentials() -> None:
    with (
        patch(
            "engine.tools.connect_adapter._kite_app_credentials",
            side_effect=EngineError("KITE_API_KEY / KITE_API_SECRET are not set"),
        ),
        pytest.raises(EngineError, match="KITE_API_KEY"),
    ):
        await connect_adapter(provider="kite")
