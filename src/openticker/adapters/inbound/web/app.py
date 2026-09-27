"""The web app, served by openticker-serve next to the REST API (ADR 30 in
docs/adr): browser sign-in, the live stream, and the built app itself.

Routes are registered in order: the ones here, then `/assets`, then a
catch-all that serves the app's page for any other GET. A new route that
isn't under `/api` must be registered before the catch-all, or the browser
gets the app's page instead.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from openticker.adapters.inbound.web import pages
from openticker.adapters.inbound.web.auth import (
    Caller,
    Principal,
    WebSettings,
    require_principal,
    require_scope,
)
from openticker.adapters.inbound.web.models import SessionResult, SignOutAllResult
from openticker.adapters.inbound.web.stream import SIGNED_OUT, StreamHub
from openticker.core.web import COOKIE_NAME, SESSION_LIFETIME
from openticker.use_cases.web_sessions import (
    redeem_sign_in_link,
    session_of,
    sign_out,
    sign_out_everywhere,
)

DIST = Path(__file__).parent / "dist"  # where `pnpm build` in ui/ writes the app
STREAM_PATH = "/api/v1/stream"
_FOREVER = "public, max-age=31536000, immutable"  # hashed file names change with content
_NOT_THE_APP = ("api/", "mcp", "webhooks/", "health", "login", "brokers/", "assets/")


def mount_web(
    app: FastAPI, *, hub: StreamHub, web: WebSettings, clock: Callable[[], datetime]
) -> None:
    @app.get("/login", include_in_schema=False)
    def login(request: Request, token: str | None = None) -> Response:
        """A sign-in link: swaps its one-time token for a session cookie."""
        user_agent = request.headers.get("user-agent")
        secret = redeem_sign_in_link(token, user_agent, clock()) if token else None
        if secret is None:
            return HTMLResponse(pages.link_expired(), status_code=400)
        response = RedirectResponse("/", status_code=303)
        _set_cookie(response, secret)
        return response

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_scope)])

    @api.get("/session")
    def session(caller: Caller, response: Response) -> SessionResult:
        """This browser's session. The app asks on every load, which also
        renews the cookie for another 30 days."""
        signed_in = _browser(caller)
        assert signed_in.secret is not None and signed_in.session is not None
        _set_cookie(response, signed_in.secret)
        return SessionResult.of(signed_in.session)

    @api.post("/session/sign-out", status_code=204)
    def end_session(caller: Caller, response: Response) -> None:
        """Signs this browser out."""
        secret = _browser(caller).secret
        assert secret is not None
        sign_out(secret, clock())
        response.delete_cookie(COOKIE_NAME, path="/")

    @api.post("/session/sign-out-all")
    def end_every_session(response: Response) -> SignOutAllResult:
        """Signs every browser out, this one too."""
        response.delete_cookie(COOKIE_NAME, path="/")
        return SignOutAllResult(ended=sign_out_everywhere(clock()))

    app.include_router(api)

    @app.websocket(STREAM_PATH)
    async def stream(socket: WebSocket) -> None:
        """Live prices and where they come from (ADR 32). Browser session only."""
        try:
            caller = await asyncio.to_thread(require_principal, socket, None, web, clock())
        except HTTPException as refused:
            await socket.close(code=SIGNED_OUT if refused.status_code == 401 else 4403)
            return
        secret = caller.secret
        assert secret is not None
        await socket.accept()
        await hub.serve(socket, alive=lambda: session_of(secret, clock()) is not None)

    @app.get("/assets/{path:path}", include_in_schema=False)
    def asset(path: str) -> FileResponse:
        file = _inside(web.dist / "assets", path)
        if file is None:
            raise HTTPException(status_code=404)
        return FileResponse(file, headers={"cache-control": _FOREVER})

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str) -> Response:
        """The app's own files (favicon), else its page for any route it
        draws itself. Anything under /api stays a JSON 404."""
        if path.startswith(_NOT_THE_APP):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index = web.dist / "index.html"
        if not index.is_file():
            return HTMLResponse(pages.not_built(), status_code=503)
        file = _inside(web.dist, path) if path else None
        return FileResponse(file or index, headers={"cache-control": "no-cache"})


def _browser(caller: Principal) -> Principal:
    if caller.via != "session":
        raise HTTPException(status_code=404, detail="no browser session: this is an API key")
    return caller


def _set_cookie(response: Response, secret: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        secret,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path="/",
        httponly=True,
        samesite="strict",
    )


def _inside(root: Path, path: str) -> Path | None:
    """The file `path` names under `root`; None when it's missing or outside."""
    file = (root / path).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file():
        return None
    return file
