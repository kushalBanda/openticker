#!/usr/bin/env python3
"""connect-adapter skill script: Kite Connect OAuth login.

Run as: uv run python plugin/skills/connect-adapter/scripts/connect_adapter.py

No server is involved - this talks to Zerodha's API directly:

1. Build the Kite login URL and open it in the user's browser.
2. Run a short-lived local HTTP listener - only for this one exchange - to
   catch Zerodha's redirect, which carries request_token.
3. Exchange request_token for an access_token directly against Kite's own
   API (lib.mechanics.kite.exchange_request_token).
4. Store the resulting api_key + access_token via lib.mechanics.state.

Only "kite" is supported. Groww has no published app-registration +
redirect flow yet.

Prints one JSON object to stdout: {"provider": "kite", "status": "connected"}
"""

import asyncio
import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PLUGIN_ROOT))

from lib.mechanics.exceptions import AuthExpiredError
from lib.mechanics.kite import exchange_request_token
from lib.mechanics.state import save_credentials

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
CALLBACK_PATH = "/kite/callback"
REPO_ROOT = _PLUGIN_ROOT.parent


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


def _kite_app_credentials() -> tuple[str, str]:
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")
    if not api_key or not api_secret:
        raise AuthExpiredError(
            "KITE_API_KEY / KITE_API_SECRET are not set. See "
            "plugin/references/kite-app-setup.md for how to register a "
            "Kite Connect app and where to put these (a .env file at the "
            "repo root)."
        )
    return api_key, api_secret


def _await_request_token() -> str:
    with HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler) as server:
        server.timeout = 120
        server.handle_request()  # blocks for exactly one request, then returns
    if not _CallbackHandler.request_token:
        raise AuthExpiredError(
            "Kite login did not complete - no request_token was received "
            f"on http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}. "
            "Retry the connect-adapter skill."
        )
    return _CallbackHandler.request_token


async def _run(provider: str) -> dict[str, str]:
    if provider != "kite":
        raise AuthExpiredError(f"provider {provider!r} is not supported yet - only 'kite' is available.")

    api_key, api_secret = _kite_app_credentials()
    login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
    webbrowser.open(login_url)
    request_token = await asyncio.to_thread(_await_request_token)
    access_token = exchange_request_token(api_key, api_secret, request_token)
    save_credentials(provider, {"api_key": api_key, "access_token": access_token})
    return {"provider": provider, "status": "connected"}


def main(argv: list[str]) -> int:
    provider = argv[argv.index("--provider") + 1] if "--provider" in argv else "kite"
    try:
        result = asyncio.run(_run(provider))
    except AuthExpiredError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
