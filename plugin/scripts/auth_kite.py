"""Connect this plugin to Kite Connect via Zerodha's own browser login.

No server is involved. This script:

1. Builds the Kite login URL and opens it in the user's browser.
2. Runs a short-lived local HTTP listener - only for this one exchange -
   to catch Zerodha's redirect, which carries `request_token`.
3. Exchanges `request_token` for an `access_token` directly against
   Kite's own API (same checksum + POST logic packages/server used to
   use, before it was deprecated and removed).
4. Stores the resulting `api_key` + `access_token` via state.py.

Run with: uv run python plugin/scripts/auth_kite.py
"""

import os
import sys
import webbrowser
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from dotenv import load_dotenv
from ingest.core.constants import KITE_BASE_URL

# state.py is a sibling script, not an installed package, so importing it
# by name requires this directory on sys.path first.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from state import save_credentials

PROVIDER = "kite"
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
CALLBACK_PATH = "/kite/callback"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _kite_app_credentials() -> tuple[str, str]:
    """Load KITE_API_KEY/KITE_API_SECRET from the repo-root .env file.

    Returns:
        The (api_key, api_secret) pair.

    Raises:
        SystemExit: Either env var is unset.
    """
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")
    if not api_key or not api_secret:
        raise SystemExit(
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
        SystemExit: No request within 120 seconds, or the redirect
            carried no request_token.
    """
    with HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler) as server:
        server.timeout = 120
        server.handle_request()  # blocks for exactly one request, then returns
    if not _CallbackHandler.request_token:
        raise SystemExit(
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
        SystemExit: Kite's API returned a non-2xx response.
    """
    checksum = sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()
    with httpx.Client(base_url=KITE_BASE_URL) as http:
        response = http.post(
            "/session/token",
            data={
                "api_key": api_key,
                "request_token": request_token,
                "checksum": checksum,
            },
        )
    if response.status_code >= 400:
        raise SystemExit(
            f"Kite login exchange failed: HTTP {response.status_code} - {response.text}"
        )
    access_token: str = response.json()["data"]["access_token"]
    return access_token


def connect() -> None:
    """Run the full Kite OAuth flow end to end and store the resulting session."""
    api_key, api_secret = _kite_app_credentials()
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
    print(f"Opening Kite login in your browser:\n{login_url}")
    print(
        f"Waiting for the redirect on http://{CALLBACK_HOST}:{CALLBACK_PORT}"
        f"{CALLBACK_PATH} ..."
    )
    webbrowser.open(login_url)
    request_token = _await_request_token()
    access_token = _exchange_for_access_token(api_key, api_secret, request_token)
    save_credentials(PROVIDER, {"api_key": api_key, "access_token": access_token})
    print("connected as Kite")


if __name__ == "__main__":
    connect()
