"""connect_adapter MCP tool (quant-engine server): Kite Connect OAuth login.

No server is involved - this talks to Zerodha's API directly, ported from
plugin/scripts/auth_kite.py:

1. Build the Kite login URL and open it in the user's browser.
2. Run a short-lived local HTTP listener - only for this one exchange -
   to catch Zerodha's redirect, which carries request_token.
3. Exchange request_token for an access_token directly against Kite's
   own API.
4. Store the resulting api_key + access_token via engine.core.state.

Only "kite" is supported. Groww has no published app-registration +
redirect flow yet (see root CLAUDE.md's ingest section).
"""

import asyncio
import os
import webbrowser
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qs, urlparse

import httpx
from dotenv import load_dotenv
from ingest.core.constants import KITE_BASE_URL
from pydantic import Field

from engine.core.exceptions import EngineError
from engine.core.state import save_credentials

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
CALLBACK_PATH = "/kite/callback"
REPO_ROOT = Path(__file__).resolve().parents[5]


def _kite_app_credentials() -> tuple[str, str]:
    """Load KITE_API_KEY/KITE_API_SECRET from the repo-root .env file.

    Returns:
        The (api_key, api_secret) pair.

    Raises:
        EngineError: Either env var is unset.
    """
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")
    if not api_key or not api_secret:
        raise EngineError(
            "KITE_API_KEY / KITE_API_SECRET are not set. See "
            "plugin/references/kite-app-setup.md for how to register a "
            "Kite Connect app and where to put these (a .env file at the "
            "repo root)."
        )
    return api_key, api_secret


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches exactly one Kite OAuth redirect and stashes its request_token."""

    request_token: str | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        token = params.get("request_token", [None])[0]
        _CallbackHandler.request_token = token
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        body = (
            b"Kite login received. You can close this tab."
            if token
            else b"Kite login failed: no request_token in the redirect."
        )
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass  # silence BaseHTTPRequestHandler's default stderr access log


def _await_request_token() -> str:
    """Run the callback listener for one request, then return its request_token.

    Returns:
        The request_token Zerodha's redirect carried.

    Raises:
        EngineError: No request within 120 seconds, or the redirect
            carried no request_token.
    """
    with HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler) as server:
        server.timeout = 120
        server.handle_request()  # blocks for exactly one request, then returns
    if not _CallbackHandler.request_token:
        raise EngineError(
            "Kite login did not complete - no request_token was received "
            f"on http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}. "
            "Retry the connect-adapter skill."
        )
    return _CallbackHandler.request_token


def _exchange_for_access_token(api_key: str, api_secret: str, request_token: str) -> str:
    """Exchange a request_token for an access_token via Kite's session API.

    Args:
        api_key: The registered Kite Connect app's API key.
        api_secret: The registered Kite Connect app's API secret.
        request_token: The token _await_request_token() caught.

    Returns:
        The resulting access_token.

    Raises:
        EngineError: Kite's API returned a non-2xx response.
    """
    checksum = sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()
    with httpx.Client(base_url=KITE_BASE_URL) as http:
        response = http.post(
            "/session/token",
            data={"api_key": api_key, "request_token": request_token, "checksum": checksum},
        )
    if response.status_code >= 400:
        raise EngineError(f"Kite login exchange failed: HTTP {response.status_code} - {response.text}")
    access_token: str = response.json()["data"]["access_token"]
    return access_token


async def connect_adapter(
    provider: Annotated[
        str, Field(description='Provider to connect. Only "kite" is supported today.')
    ] = "kite",
) -> dict[str, Any]:
    """Run a provider's OAuth connect flow and store the resulting session.

    Opens the provider's login page in the user's browser and waits (up to
    120s) for the OAuth redirect - this is an interactive, human-in-the-loop
    call, not a silent background one.

    Returns:
        {"provider": provider, "status": "connected"} on success.

    Raises:
        EngineError: Unsupported provider, missing app credentials, or the
            OAuth exchange failed.
    """
    if provider != "kite":
        raise EngineError(
            f"provider {provider!r} is not supported yet - only 'kite' is available."
        )

    api_key, api_secret = _kite_app_credentials()
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
    webbrowser.open(login_url)
    request_token = await asyncio.to_thread(_await_request_token)
    access_token = _exchange_for_access_token(api_key, api_secret, request_token)
    save_credentials(provider, {"api_key": api_key, "access_token": access_token})
    return {"provider": provider, "status": "connected"}
