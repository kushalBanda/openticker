from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

import httpx
import pytest

from openticker.adapters.brokers.zerodha import auth
from openticker.ports.models import EXCHANGE_TIMEZONE


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.posted_with: dict[str, str] | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        pass

    def post(self, path: str, data: dict[str, str]) -> _FakeResponse:
        self.posted_with = data
        return self._response


def test_exchange_request_token_maps_kite_response_to_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeClient(_FakeResponse(200, {"data": {"access_token": "the-access-token"}}))
    monkeypatch.setattr(httpx, "Client", lambda base_url: fake_client)

    credentials = auth.exchange_request_token(
        api_key="key123",
        api_secret="secret456",
        request_token="reqtok789",
        now=datetime(2026, 10, 3, 11, 47, tzinfo=UTC),  # Saturday 17:17 IST
    )

    assert credentials.broker == "zerodha"
    assert credentials.access_token == "the-access-token"
    assert credentials.refresh_token is None
    assert credentials.expires_at == datetime(2026, 10, 4, 0, 30, tzinfo=UTC)  # Sunday 06:00 IST
    assert fake_client.posted_with is not None
    assert fake_client.posted_with["api_key"] == "key123"
    assert fake_client.posted_with["request_token"] == "reqtok789"


def test_exchange_request_token_raises_on_kite_error_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeClient(_FakeResponse(403, {"error_type": "TokenException"}))
    monkeypatch.setattr(httpx, "Client", lambda base_url: fake_client)

    with pytest.raises(auth.KiteAuthError):
        auth.exchange_request_token(
            api_key="k", api_secret="s", request_token="r", now=datetime(2026, 10, 3, tzinfo=UTC)
        )


def test_a_session_ends_at_the_next_0600_ist() -> None:
    def ist(hour: int, minute: int) -> datetime:
        return datetime(2026, 10, 3, hour, minute, tzinfo=EXCHANGE_TIMEZONE)

    next_morning = datetime(2026, 10, 4, 6, 0, tzinfo=EXCHANGE_TIMEZONE)
    assert auth.session_ends(ist(17, 17)) == next_morning
    assert auth.session_ends(ist(5, 59)) == ist(6, 0)  # before the logout: that same morning
    assert auth.session_ends(ist(6, 0)) == next_morning
