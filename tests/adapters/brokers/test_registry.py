import pytest

from openticker.adapters.brokers.registry import UnknownBrokerError, get_adapter, get_login_url
from openticker.adapters.brokers.zerodha.adapter import ZerodhaAdapter
from openticker.ports.models import Credentials
from openticker.storage.sqlite.credentials_repo import save_credentials


def test_get_adapter_rejects_unknown_broker() -> None:
    with pytest.raises(UnknownBrokerError):
        get_adapter("nonexistent")


def test_get_login_url_rejects_unknown_broker() -> None:
    with pytest.raises(UnknownBrokerError):
        get_login_url("nonexistent")


def test_zerodha_adapter_picks_up_the_stored_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KITE_API_KEY", "key")
    monkeypatch.setenv("KITE_API_SECRET", "secret")
    save_credentials(
        Credentials(broker="zerodha", access_token="stored-token", refresh_token=None, expires_at=None)
    )

    adapter = get_adapter("zerodha")

    assert isinstance(adapter, ZerodhaAdapter)
    assert adapter._session_token() == "stored-token"
