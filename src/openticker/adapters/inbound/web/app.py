"""The web app, served by openticker-serve next to the REST API (ADR 30 in
docs/adr): browser sign-in, the live stream, and the built app itself.

Routes are registered in order: the ones here, then `/assets`, then a
catch-all that serves the app's page for any other GET. A new route that
isn't under `/api` must be registered before the catch-all, or the browser
gets the app's page instead.
"""

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from openticker.adapters.brokers.registry import (
    BrokerConfigError,
    UnknownBrokerError,
    get_adapter,
    get_login_url,
    require_broker,
)
from openticker.adapters.inbound.web import pages
from openticker.adapters.inbound.web.auth import (
    Caller,
    Principal,
    WebSettings,
    require_principal,
    require_scope,
)
from openticker.adapters.inbound.web.models import (
    AccountResult,
    ApiKeyResult,
    ApiKeysResult,
    BrokerSessionResult,
    CreatedKeyResult,
    InstrumentStatusResult,
    NotificationsResult,
    ResetResult,
    SessionResult,
    SetupResult,
    SignOutAllResult,
    TodayResult,
)
from openticker.adapters.inbound.web.stream import SIGNED_OUT, StreamHub
from openticker.composition import capital_cap, notifications_on, order_broker, sandbox_settings
from openticker.core.web import COOKIE_NAME, SESSION_LIFETIME
from openticker.events.bus import EventBus
from openticker.ports.errors import BrokerError
from openticker.storage.calendar_file import load_calendar
from openticker.storage.charges_file import load_charge_book
from openticker.use_cases.api_keys import create_api_key, get_api_keys, revoke_user_key
from openticker.use_cases.connect_broker import connect_broker, disconnect_broker
from openticker.use_cases.reset_paper_account import CONFIRMATION, reset_paper_account
from openticker.use_cases.settings_state import broker_session as session_of_broker
from openticker.use_cases.settings_state import charge_rates, instrument_status
from openticker.use_cases.setup_state import setup_state
from openticker.use_cases.today import today
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
    app: FastAPI,
    *,
    events: EventBus,
    env: Mapping[str, str],
    hub: StreamHub,
    web: WebSettings,
    clock: Callable[[], datetime],
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

    @api.get("/brokers/{broker}/session")
    def broker_session(broker: str) -> BrokerSessionResult:
        """Whether the broker is connected and until when. Never the token."""
        require_broker(broker)
        return BrokerSessionResult.of(
            session_of_broker(broker, clock()), _configured(broker), _callback_url(web, broker)
        )

    @api.delete("/brokers/{broker}/session", status_code=204)
    def disconnect(broker: str, caller: Caller) -> None:
        """Deletes the stored broker session. Live prices stop until the next login."""
        disconnect_broker(require_broker(broker), events, caller.triggered_by)

    @api.get("/instruments/status")
    def instruments_status() -> InstrumentStatusResult:
        """When the instrument list was last synced, and contracts per exchange."""
        return InstrumentStatusResult.of(instrument_status())

    @api.get("/keys")
    def keys() -> ApiKeysResult:
        """Active API keys: the user's, and those OpenTicker made for running
        scripts and agent jobs. Never a key itself."""
        active = [key for key in get_api_keys() if key.revoked_at is None]
        return ApiKeysResult(keys=[ApiKeyResult.of(key) for key in active])

    @api.post("/keys", status_code=201)
    def create_key(body: CreateKeyBody) -> CreatedKeyResult:
        """A new full-scope key, returned this once."""
        stored, secret = create_api_key(body.name, clock())
        return CreatedKeyResult(key=ApiKeyResult.of(stored), secret=secret)

    @api.delete("/keys/{name}", status_code=204)
    def revoke_key(name: str) -> None:
        """Revokes a key the user made; it stops working at once."""
        revoke_user_key(name, clock())

    @api.get("/account")
    def account() -> AccountResult:
        """The paper account's settings, from .env, and its charge rates."""
        return AccountResult.of(
            sandbox_settings(env), capital_cap(env), charge_rates(load_charge_book())
        )

    @api.post("/account/reset")
    def reset(body: ResetBody, caller: Caller) -> ResetResult:
        """Deletes every paper order, trade and position and restores the
        starting capital (ADR 37). Refused while a strategy or script runs."""
        done = reset_paper_account(
            body.confirm,
            sandbox_settings(env).starting_capital,
            events,
            clock(),
            caller.triggered_by,
        )
        return ResetResult(
            capital=done.capital, orders=done.orders, trades=done.trades, positions=done.positions
        )

    @api.get("/today")
    def today_route(broker: str, caller: Caller) -> TodayResult:
        """The Dashboard's Today: the day's P&L after charges, its minute line,
        and, for a browser, what happened since its previous visit today."""
        visit = caller.session.previous_visit_at if caller.session else None
        return TodayResult.of(
            today(order_broker(require_broker(broker), env, clock), visit, load_calendar(), clock())
        )

    @api.get("/setup")
    def setup(broker: str) -> SetupResult:
        """The first-run checklist: broker connected, instruments synced, an
        agent seen, a first paper fill."""
        return SetupResult.of(broker, setup_state(require_broker(broker), clock()))

    @api.get("/notifications")
    def notifications() -> NotificationsResult:
        """Whether Slack and email are set up. Never their settings."""
        slack, email = notifications_on(env)
        return NotificationsResult(slack=slack, email=email)

    app.include_router(api)

    @app.get("/brokers/{broker}/callback", include_in_schema=False)
    def broker_callback(
        request: Request,
        broker: str,
        request_token: str | None = None,
        status: str | None = None,
        bounced: bool = False,
    ) -> Response:
        """The broker's login redirect (ADR 33): stores the session, then
        back to Settings. Only a signed-in browser's login is kept.

        The session cookie is SameSite=Strict, so the browser leaves it off a
        redirect that comes from the broker's site. The first answer is a
        page of ours that opens the same URL again: that navigation starts
        here, and carries the cookie."""
        if COOKIE_NAME not in request.cookies and not bounced:
            again = f"{request.url.path}?{urlencode({**request.query_params, 'bounced': '1'})}"
            return HTMLResponse(pages.bounce(again))
        try:
            caller = require_principal(request, None, web, clock())
        except HTTPException:
            return HTMLResponse(pages.sign_in_first(), status_code=401)
        if status != "success" or not request_token:
            return _back(connect_error=f"{broker} login didn't finish: try again")
        try:
            connect_broker(
                get_adapter(require_broker(broker)), request_token, events, caller.triggered_by
            )
        except (BrokerError, BrokerConfigError, UnknownBrokerError) as exc:
            return _back(connect_error=str(exc))
        return _back(connected=broker)

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


class CreateKeyBody(BaseModel):
    name: str = Field(description="1-40 lowercase letters, digits, '-' or '_'.")


class ResetBody(BaseModel):
    confirm: str = Field(description=f"Must be {CONFIRMATION!r}.")


def _configured(broker: str) -> bool:
    try:
        get_login_url(broker)
    except (BrokerConfigError, UnknownBrokerError):
        return False
    return True


def _callback_url(web: WebSettings, broker: str) -> str:
    return f"{web.own_origin}/brokers/{broker}/callback"


def _back(**flag: str) -> RedirectResponse:
    return RedirectResponse(f"/settings?{urlencode(flag)}", status_code=303)


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
