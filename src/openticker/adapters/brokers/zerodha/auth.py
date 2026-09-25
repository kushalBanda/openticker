"""OAuth exchange — translation of Kite's login flow into Credentials (ADR 5 in docs/adr)."""

from hashlib import sha256
from http import HTTPStatus

import httpx

from openticker.ports.errors import BrokerError
from openticker.ports.models import Credentials

KITE_BASE_URL = "https://api.kite.trade"
KITE_LOGIN_URL = "https://kite.zerodha.com/connect/login"


class KiteAuthError(BrokerError):
    """Kite rejected the login exchange."""


def build_login_url(api_key: str) -> str:
    return f"{KITE_LOGIN_URL}?v=3&api_key={api_key}"


def exchange_request_token(api_key: str, api_secret: str, request_token: str) -> Credentials:
    """Exchange a request_token (from Zerodha's OAuth redirect) for an access_token."""
    checksum = sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()
    with httpx.Client(base_url=KITE_BASE_URL) as client:
        response = client.post(
            "/session/token",
            data={"api_key": api_key, "request_token": request_token, "checksum": checksum},
        )
    if response.status_code >= HTTPStatus.BAD_REQUEST:
        raise KiteAuthError(
            f"Kite login exchange failed: HTTP {response.status_code} - {response.text}"
        )
    access_token: str = response.json()["data"]["access_token"]
    return Credentials(
        broker="zerodha",
        access_token=access_token,
        refresh_token=None,  # Kite Connect does not issue a refresh token; sessions are re-authenticated daily
        expires_at=None,
    )
