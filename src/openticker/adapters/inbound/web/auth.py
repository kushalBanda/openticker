"""Who is calling: an API key, or a browser signed in to the web app (ADR 17
and ADR 31 in docs/adr).

A key is sent in `X-API-Key`. Without one, the `ot_session` cookie is tried,
but only on a request to a loopback name on this server's port, and, for a
request that changes something, only from this server's own pages. A browser
session has the full scope, and what it does is recorded as done by `ui`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader
from starlette.requests import HTTPConnection

from openticker.adapters.inbound.scopes import TOOL_ROUTES, refusal
from openticker.core.web import COOKIE_NAME, host_allowed, origin_allowed
from openticker.storage.sqlite import runs_repo
from openticker.storage.sqlite.web_repo import WebSession
from openticker.use_cases.api_keys import FULL_SCOPE, authenticate
from openticker.use_cases.web_sessions import session_of

UI = "ui"
API_KEY_HEADER = "X-API-Key"
KEY_MISSING = (
    f"missing or invalid API key: send one in the {API_KEY_HEADER} header "
    "(create one with `openticker-serve keys create <name>`)"
)
SIGN_IN = "open the link openticker-serve printed, or run `openticker-serve ui login` for a new one"
NOT_SIGNED_IN = f"not signed in: {SIGN_IN}; or send an API key in the {API_KEY_HEADER} header"
SESSION_ENDED = f"this browser's session has ended: {SIGN_IN}"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class WebSettings:
    own_origin: str  # http://127.0.0.1:8750
    port: int
    dev_origin: str | None  # the Vite dev server's origin, with --dev
    dist: Path  # the built app


@dataclass(frozen=True)
class Principal:
    name: str  # the key's name, or "ui"
    scope: str
    via: Literal["key", "session"]
    triggered_by: str  # as the audit log records it: "ui", "rest:<name>", or the key's scope
    session: WebSession | None = None
    secret: str | None = None  # the session cookie, to sign this browser out


def require_principal(
    connection: HTTPConnection, key: str | None, web: WebSettings | None, now: datetime
) -> Principal:
    """A key when one is sent; else, with the web app mounted, the session
    cookie. Raises 401 when neither is valid, 403 for a cookie sent from
    somewhere a browser session isn't accepted."""
    if key or web is None:
        return _key_principal(key)
    secret = connection.cookies.get(COOKIE_NAME)
    if not secret:
        raise HTTPException(status_code=401, detail=NOT_SIGNED_IN)
    is_socket = connection.scope["type"] == "websocket"
    method = "WEBSOCKET" if is_socket else connection.scope["method"]
    why = browser_refusal(connection, web, check_origin=method not in _SAFE_METHODS)
    if why is not None:
        raise HTTPException(status_code=403, detail=why)
    session = session_of(secret, now)
    if session is None:
        raise HTTPException(status_code=401, detail=SESSION_ENDED)
    return Principal(UI, FULL_SCOPE, "session", UI, session, secret)


def browser_refusal(connection: HTTPConnection, web: WebSettings, check_origin: bool) -> str | None:
    """Why a request carrying the session cookie is refused, or None. The
    Host check stops a page that rebinds its own name to this machine; the
    Origin check stops another site's page sending changes."""
    if not host_allowed(connection.headers.get("host"), web.port):
        return "a browser session is accepted only at this machine's own address"
    if check_origin and not origin_allowed(
        connection.headers.get("origin"), web.own_origin, web.dev_origin
    ):
        return "a browser session is accepted only from OpenTicker's own pages"
    return None


def _key_principal(key: str | None) -> Principal:
    stored = authenticate(key) if key else None
    if stored is None:
        raise HTTPException(status_code=401, detail=KEY_MISSING)
    caller = stored.scope if stored.scope != FULL_SCOPE else f"rest:{stored.name}"
    return Principal(stored.name, stored.scope, "key", caller)


_api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


def require_caller(
    request: Request, key: Annotated[str | None, Depends(_api_key_header)]
) -> Principal:
    """The route dependency: `create_app` keeps the web settings (None
    without the web app) and the clock on the app's state."""
    state = request.app.state
    return require_principal(request, key, state.web, state.clock())


Caller = Annotated[Principal, Depends(require_caller)]


def require_scope(request: Request, caller: Caller) -> Principal:
    """Holds a scoped key to its routes (adapters/inbound/scopes.py). A
    route whose body a scope checks calls `refuse_outside_scope` too."""
    path = getattr(request.scope.get("route"), "path", None)
    why = refusal(
        caller.scope,
        request.method,
        path,
        request.path_params,
        _strategy_of_run,
        whole_call=False,
    )
    if why is not None:
        raise HTTPException(status_code=403, detail=why)
    return caller


def refuse_outside_scope(caller: Principal, tool: str, arguments: Mapping[str, object]) -> None:
    """Holds a scoped key to what the body of `tool`'s route asks for, as
    MCP does with the tool's arguments: a review's brain appends are about
    its own strategy only."""
    method, path = TOOL_ROUTES[tool]
    why = refusal(caller.scope, method, path, arguments, _strategy_of_run)
    if why is not None:
        raise HTTPException(status_code=403, detail=why)


def _strategy_of_run(run_id: str) -> str | None:
    run = runs_repo.find_run(run_id)
    return run.strategy_id if run is not None else None
