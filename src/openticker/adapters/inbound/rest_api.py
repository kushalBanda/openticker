"""REST API: the MCP tools as HTTP routes, each a thin call into use_cases,
returning the same result shapes. Every route under /api/v1 needs an API key
in the `X-API-Key` header (ADR 17 in docs/adr). A hosted script's key reaches
only prices, orders and positions (ADR 25). Signal strategies' alert URLs,
under /webhooks, are authenticated by the token in the URL instead (ADR 24).

Routes are plain `def`: FastAPI runs them on its thread pool, which keeps the
use cases sync (ADR 2 in docs/adr).
"""

import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from importlib.metadata import version
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from openticker.adapters.brokers.registry import (
    BrokerConfigError,
    UnknownBrokerError,
    get_adapter,
    get_login_url,
    require_broker,
)
from openticker.adapters.inbound.mcp_models import (
    ALERT_NEXT_STEP,
    ALERT_PATH,
    AlertResult,
    AuditLogResult,
    BarsResult,
    CancelOrderResult,
    ConnectResult,
    DeleteScriptResult,
    DeleteStrategyResult,
    FundsResult,
    LoginUrlResult,
    MarketStatusesResult,
    MarketStatusResult,
    ModifyOrderResult,
    OptionChainResult,
    OrderbookEntryResult,
    OrderbookResult,
    PlaceOrderResult,
    PositionsResult,
    QuoteResult,
    RiskCheckResult,
    ScriptCommandResult,
    ScriptDetailResult,
    ScriptLogsResult,
    ScriptResult,
    ScriptScheduleDefinition,
    ScriptsResult,
    SearchResult,
    SignalStrategyDefinition,
    StrategiesResult,
    StrategyCommandResult,
    StrategyDefinition,
    StrategyPreviewResult,
    StrategyResult,
    StrategyRunResult,
    StrategyRunsResult,
    StrategySignalsResult,
    StrategySummary,
    SyncResult,
    TradebookResult,
    WebhookResult,
)
from openticker.composition import SandboxConfigError, capital_cap, order_broker
from openticker.core.calendar.calendar import CalendarError
from openticker.core.options.underlyings import UnsupportedUnderlyingError
from openticker.core.orders.models import OrderChanges, OrderRequest, OrderStatus, OrderType
from openticker.core.scripts.models import InvalidScriptError
from openticker.core.strategies.legs import LegResolutionError
from openticker.core.strategies.models import InvalidStrategyError
from openticker.events.bus import EventBus
from openticker.ports.errors import BrokerError
from openticker.ports.models import (
    EXCHANGE_TIMEZONE,
    Exchange,
    InstrumentType,
    Interval,
    Product,
    Side,
)
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite.api_keys_repo import StoredApiKey
from openticker.storage.sqlite.scripts_repo import DuplicateScriptNameError
from openticker.storage.sqlite.strategies_repo import DuplicateStrategyNameError
from openticker.use_cases.api_keys import SCRIPT_SCOPE_PREFIX, authenticate
from openticker.use_cases.cancel_order import cancel_order
from openticker.use_cases.connect_broker import connect_broker
from openticker.use_cases.errors import UnknownOrderError
from openticker.use_cases.evaluate_risk import evaluate_risk
from openticker.use_cases.get_audit_log import get_audit_log
from openticker.use_cases.get_funds import get_funds
from openticker.use_cases.get_historical_bars import get_historical_bars
from openticker.use_cases.get_market_status import get_market_status
from openticker.use_cases.get_option_chain import NoOptionsError, get_option_chain
from openticker.use_cases.get_order_status import get_order_status
from openticker.use_cases.get_orderbook import get_orderbook
from openticker.use_cases.get_positions import get_positions
from openticker.use_cases.get_quote import get_quote
from openticker.use_cases.get_tradebook import get_tradebook, session_start
from openticker.use_cases.modify_order import modify_order
from openticker.use_cases.place_order import place_order
from openticker.use_cases.resolve_instrument import UnknownInstrumentError, resolve_instrument
from openticker.use_cases.scripts import manage as scripts
from openticker.use_cases.scripts.manage import (
    ScriptRunningError,
    ScriptStateError,
    UnknownScriptError,
)
from openticker.use_cases.search_instruments import search_instruments
from openticker.use_cases.strategies import control
from openticker.use_cases.strategies.control import (
    StrategyLockedError,
    StrategyStateError,
    UnknownRunError,
)
from openticker.use_cases.strategies.define import (
    StrategyKindError,
    StrategyRunningError,
    UnknownStrategyError,
    create_strategy,
    delete_strategy,
    get_strategy,
    list_strategies,
    preview_strategy,
    update_strategy,
)
from openticker.use_cases.strategies.signals import SignalResult, accept_signal
from openticker.use_cases.sync_instruments import sync_instruments

API_KEY_HEADER = "X-API-Key"

# The errors the MCP server turns into agent-facing messages (ADR 7 in docs/adr),
# here as HTTP statuses carrying the same message.
_ERROR_STATUSES: tuple[tuple[type[Exception], int], ...] = (
    (UnknownInstrumentError, 404),
    (UnknownBrokerError, 404),
    (UnsupportedUnderlyingError, 404),
    (NoOptionsError, 404),
    (UnknownOrderError, 404),
    (UnknownStrategyError, 404),
    (LegResolutionError, 404),
    (UnknownRunError, 404),
    (UnknownScriptError, 404),
    (DuplicateStrategyNameError, 409),
    (StrategyRunningError, 409),
    (StrategyLockedError, 409),
    (StrategyStateError, 409),
    (StrategyKindError, 409),
    (DuplicateScriptNameError, 409),
    (ScriptRunningError, 409),
    (ScriptStateError, 409),
    (InvalidStrategyError, 422),
    (InvalidScriptError, 422),
    (BrokerError, 502),
    (BrokerConfigError, 503),
    (SandboxConfigError, 503),
    (CalendarError, 503),
)

_NEXT_STEP = {
    OrderStatus.FILLED: "GET /api/v1/positions shows the position and its P&L.",
    OrderStatus.PENDING: "Rests until a live price crosses it; fills while openticker-serve "
    "runs. DELETE /api/v1/orders/{order_id} withdraws it.",
}

_STRATEGY_NEXT_STEP = (
    "GET /api/v1/strategies/{strategy_id}/preview shows the contracts it would trade now; "
    "POST /api/v1/strategies/{strategy_id}/start enters it."
)
_COMMAND_NEXT_STEP = (
    "openticker-serve carries this out within about a second; "
    "GET /api/v1/strategies/{strategy_id}/runs shows the outcome."
)
_SCRIPT_COMMAND_NEXT_STEP = (
    "openticker-serve carries this out within about a second; "
    "GET /api/v1/scripts/{script_id}/logs shows its output."
)
_PREVIEW_NEXT_STEP = (
    "Nothing was placed. Change the legs with PUT /api/v1/strategies/{strategy_id}."
)

_api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


def require_api_key(key: Annotated[str | None, Depends(_api_key_header)]) -> StoredApiKey:
    stored = authenticate(key) if key else None
    if stored is None:
        raise HTTPException(
            status_code=401,
            detail=f"missing or invalid API key: send one in the {API_KEY_HEADER} header "
            "(create one with `openticker-serve keys create <name>`)",
        )
    return stored


ApiKey = Annotated[StoredApiKey, Depends(require_api_key)]

# What a hosted script's key reaches (ADR 25 in docs/adr): prices, and placing,
# reading, changing and cancelling orders. Never broker login, strategies or scripts.
_SCRIPT_ROUTES = frozenset(
    {
        ("GET", "/api/v1/instruments"),
        ("GET", "/api/v1/quote"),
        ("GET", "/api/v1/bars"),
        ("GET", "/api/v1/option-chain"),
        ("GET", "/api/v1/market-status"),
        ("POST", "/api/v1/risk/evaluate"),
        ("POST", "/api/v1/orders"),
        ("GET", "/api/v1/orders"),
        ("DELETE", "/api/v1/orders/{order_id}"),
        ("PATCH", "/api/v1/orders/{order_id}"),
        ("GET", "/api/v1/orders/{order_id}"),
        ("GET", "/api/v1/trades"),
        ("GET", "/api/v1/positions"),
        ("GET", "/api/v1/funds"),
    }
)


def require_scope(request: Request, key: ApiKey) -> StoredApiKey:
    if key.scope.startswith(SCRIPT_SCOPE_PREFIX):
        path = getattr(request.scope.get("route"), "path", None)
        if (request.method, path) not in _SCRIPT_ROUTES:
            raise HTTPException(
                status_code=403,
                detail="a script's key reaches prices, orders and positions only",
            )
    return key


def _caller(key: StoredApiKey) -> str:
    """Who an order came from, as the audit log records it: script:<id> for
    a hosted script, rest:<key name> otherwise."""
    return key.scope if key.scope.startswith(SCRIPT_SCOPE_PREFIX) else f"rest:{key.name}"
Broker = Annotated[str, Query(description="Broker name, e.g. zerodha.")]
Symbol = Annotated[str, Query(description="Standardized symbol, e.g. RELIANCE, NIFTY 50.")]
ExchangeQuery = Annotated[Exchange, Query()]


class BrokerBody(BaseModel):
    broker: str


class ConnectBody(BaseModel):
    broker: str
    request_token: str = Field(description="From the redirect URL after login.")


class StrategyBody(BaseModel):
    name: str = Field(description="Unique among your strategies.")
    definition: StrategyDefinition


class SignalStrategyBody(BaseModel):
    name: str = Field(description="Unique among your strategies.")
    definition: SignalStrategyDefinition


class ScriptBody(BaseModel):
    name: str = Field(description="Unique among your scripts.")
    source: str = Field(description="The whole Python file.")


class WebhookBody(BaseModel):
    broker: str
    allowed_ips: list[str] = Field(
        default=[], max_length=20, description="Addresses or CIDR ranges; empty allows any."
    )


# How an alert's outcome is answered. An ignored alert is a success: the
# sender did nothing wrong, and a failure would only make it retry.
_ALERT_STATUSES = {
    SignalResult.ACCEPTED: 200,
    SignalResult.IGNORED: 200,
    SignalResult.REFUSED: 400,
    SignalResult.LOCKED: 403,
    SignalResult.FORBIDDEN: 403,
    SignalResult.UNKNOWN: 404,
    SignalResult.RATE_LIMITED: 429,
}


async def _raw_body(request: Request) -> bytes:
    return await request.body()


_ALERT_TOKEN = re.compile(re.escape(ALERT_PATH) + r"/[^/?\s\"]+")


class HideAlertTokens(logging.Filter):
    """Keeps alert URL tokens out of the server's access log: the path is the
    credential (ADR 24 in docs/adr)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _ALERT_TOKEN.sub(ALERT_PATH + "/[token]", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        if isinstance(record.msg, str):
            record.msg = _ALERT_TOKEN.sub(ALERT_PATH + "/[token]", record.msg)
        return True


class PlaceOrderBody(BaseModel):
    broker: str
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int = Field(ge=1, description="Units, not lots.")
    product: Product
    order_type: OrderType = OrderType.MARKET
    price: float | None = Field(default=None, gt=0, description="LIMIT and SL only.")
    trigger_price: float | None = Field(default=None, gt=0, description="SL and SL-M only.")


class ModifyOrderBody(BaseModel):
    broker: str
    quantity: int | None = Field(default=None, ge=1, description="Omit to keep it.")
    price: float | None = Field(default=None, gt=0, description="LIMIT and SL only.")
    trigger_price: float | None = Field(default=None, gt=0, description="SL and SL-M only.")


class RiskBody(BaseModel):
    broker: str
    symbol: str
    exchange: Exchange
    side: Side
    quantity: int = Field(ge=1)
    entry_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    target: float | None = Field(default=None, gt=0)
    capital_cap: float | None = Field(default=None, gt=0)


class HealthResult(BaseModel):
    status: str
    version: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_app(
    events: EventBus, env: Mapping[str, str], clock: Callable[[], datetime] = _utc_now
) -> FastAPI:
    app = FastAPI(title="OpenTicker", version=version("openticker"))
    for error, status in _ERROR_STATUSES:
        app.add_exception_handler(error, _responder(status))

    @app.get("/health")
    def health() -> HealthResult:
        """Unauthenticated: whether the server is up."""
        return HealthResult(status="ok", version=version("openticker"))

    @app.post(ALERT_PATH + "/{token}")
    def alert(
        token: str, request: Request, body: Annotated[bytes, Depends(_raw_body)]
    ) -> JSONResponse:
        """A signal strategy's alert URL: no API key, the token is the credential."""
        outcome = accept_signal(
            token, request.client.host if request.client else None, body, clock()
        )
        return JSONResponse(
            status_code=_ALERT_STATUSES[outcome.result],
            content=AlertResult(status=outcome.result.value, message=outcome.message).model_dump(),
        )

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_scope)])

    @api.get("/brokers/{broker}/login-url")
    def login_url(broker: str) -> LoginUrlResult:
        return LoginUrlResult(
            broker=broker,
            login_url=get_login_url(broker),
            next_step="After login, POST the redirect's request_token to /api/v1/brokers/connect.",
        )

    @api.post("/brokers/connect")
    def connect(body: ConnectBody) -> ConnectResult:
        connect_broker(get_adapter(body.broker), body.request_token)
        return ConnectResult(
            broker=body.broker,
            connected=True,
            next_step="POST /api/v1/instruments/sync if it hasn't run today.",
        )

    @api.post("/instruments/sync")
    def sync(body: BrokerBody) -> SyncResult:
        count = sync_instruments(body.broker, get_adapter(body.broker), events)
        return SyncResult(broker=body.broker, instrument_count=count)

    @api.get("/instruments")
    def search(
        query: Annotated[str, Query(min_length=1)],
        exchange: Exchange | None = None,
        instrument_type: InstrumentType | None = None,
        include_expired: bool = False,
        limit: Annotated[int, Query(ge=1, le=500)] = 20,
    ) -> SearchResult:
        found = search_instruments(
            query,
            exchange,
            instrument_type,
            include_expired,
            today=datetime.now(EXCHANGE_TIMEZONE).date(),
            limit=limit + 1,
        )
        return SearchResult.of(found, limit)

    @api.get("/quote")
    def quote(broker: Broker, symbol: Symbol, exchange: ExchangeQuery) -> QuoteResult:
        return QuoteResult.of(get_quote(get_adapter(broker), symbol, exchange.value))

    @api.get("/bars")
    def bars(
        broker: Broker,
        symbol: Symbol,
        exchange: ExchangeQuery,
        interval: Interval,
        start_date: date,
        end_date: date,
        max_bars: Annotated[int, Query(ge=1, le=5000)] = 200,
    ) -> BarsResult:
        found = get_historical_bars(
            get_adapter(broker), symbol, exchange.value, interval.value, start_date, end_date
        )
        return BarsResult.of(symbol, exchange, interval, found, max_bars)

    @api.get("/option-chain")
    def option_chain(
        broker: Broker,
        underlying: Annotated[str, Query(description="e.g. NIFTY 50, SENSEX, RELIANCE.")],
        exchange: ExchangeQuery,
        expiry: date | None = None,
        strike_count: Annotated[int, Query(ge=1, le=50)] = 10,
        interest_rate: Annotated[float, Query(ge=0, le=20, description="Percent.")] = 0.0,
    ) -> OptionChainResult:
        now = datetime.now(UTC)
        chain, expiries = get_option_chain(
            get_adapter(broker),
            underlying,
            exchange.value,
            expiry,
            strike_count,
            interest_rate / 100,
            now,
        )
        return OptionChainResult.of(chain, expiries, now)

    @api.post("/orders")
    def create_order(body: PlaceOrderBody, key: ApiKey) -> PlaceOrderResult:
        """Paper trade in the local sandbox; nothing is sent to the broker. A
        rejection is still a 200, with the reason in the body."""
        request = OrderRequest(
            instrument=resolve_instrument(body.symbol, body.exchange.value),
            side=body.side,
            quantity=body.quantity,
            product=body.product,
            order_type=body.order_type,
            price=body.price,
            trigger_price=body.trigger_price,
            triggered_by=_caller(key),
        )
        result = place_order(
            request,
            order_broker(body.broker, env, clock),
            events,
            capital_cap(env),
            load_calendar(),
            clock(),
        )
        return PlaceOrderResult.of(
            request,
            result,
            _NEXT_STEP.get(result.status, "Fix what the reason says and place the order again."),
        )

    @api.delete("/orders/{order_id}")
    def delete_order(order_id: str, broker: Broker, key: ApiKey) -> CancelOrderResult:
        """Withdraws a PENDING order; anything else is left as it is."""
        result = cancel_order(order_id, order_broker(broker, env, clock), events, _caller(key))
        return CancelOrderResult.of(order_id, result)

    @api.patch("/orders/{order_id}")
    def patch_order(order_id: str, body: ModifyOrderBody, key: ApiKey) -> ModifyOrderResult:
        """Changes a PENDING order's quantity, price or trigger; never fills it."""
        sandbox = order_broker(body.broker, env, clock)
        result = modify_order(
            order_id,
            OrderChanges(
                quantity=body.quantity, price=body.price, trigger_price=body.trigger_price
            ),
            sandbox,
            events,
            capital_cap(env),
            load_calendar(),
            clock(),
            _caller(key),
        )
        return ModifyOrderResult.of(order_id, result, get_order_status(sandbox, order_id))

    @api.get("/market-status")
    def market_status(exchange: Exchange | None = None) -> MarketStatusesResult:
        exchanges = [exchange] if exchange is not None else list(Exchange)
        statuses = get_market_status(exchanges, clock())
        return MarketStatusesResult(exchanges=[MarketStatusResult.of(s) for s in statuses])

    @api.get("/orders")
    def orderbook(
        broker: Broker, limit: Annotated[int, Query(ge=1, le=200)] = 20
    ) -> OrderbookResult:
        return OrderbookResult.of(get_orderbook(order_broker(broker, env, clock), limit))

    @api.get("/orders/{order_id}")
    def order_status(order_id: str, broker: Broker) -> OrderbookEntryResult:
        return OrderbookEntryResult.of(get_order_status(order_broker(broker, env, clock), order_id))

    @api.get("/trades")
    def tradebook(
        broker: Broker, limit: Annotated[int, Query(ge=1, le=500)] = 50
    ) -> TradebookResult:
        """Today's fills, newest first."""
        now = clock()
        return TradebookResult.of(
            get_tradebook(order_broker(broker, env, clock), limit, now), session_start(now)
        )

    @api.get("/positions")
    def positions(broker: Broker, include_closed: bool = False) -> PositionsResult:
        return PositionsResult.of(get_positions(order_broker(broker, env, clock)), include_closed)

    @api.get("/funds")
    def funds(broker: Broker) -> FundsResult:
        return FundsResult.of(get_funds(order_broker(broker, env, clock)))

    @api.post("/risk/evaluate")
    def risk(body: RiskBody) -> RiskCheckResult:
        """Places nothing."""
        return RiskCheckResult.of(
            evaluate_risk(
                get_adapter(body.broker),
                body.symbol,
                body.exchange.value,
                body.side,
                body.quantity,
                body.entry_price,
                body.stop_loss,
                body.target,
                body.capital_cap,
            )
        )

    @api.get("/audit")
    def audit(
        event_type: str | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 20
    ) -> AuditLogResult:
        return AuditLogResult.of(get_audit_log(limit, event_type))

    @api.post("/strategies")
    def new_strategy(body: StrategyBody) -> StrategyResult:
        """Saves a definition. Places nothing."""
        stored = create_strategy(body.name, body.definition.to_spec(), clock())
        return StrategyResult.of(stored, _STRATEGY_NEXT_STEP)

    @api.get("/strategies")
    def strategies() -> StrategiesResult:
        return StrategiesResult(strategies=[StrategySummary.of(s) for s in list_strategies()])

    @api.get("/strategies/{strategy_id}")
    def strategy(strategy_id: str) -> StrategyResult:
        return StrategyResult.of(get_strategy(strategy_id))

    @api.put("/strategies/{strategy_id}")
    def change_strategy(strategy_id: str, body: StrategyBody) -> StrategyResult:
        """Replaces the whole definition."""
        stored = update_strategy(strategy_id, body.name, body.definition.to_spec(), clock())
        return StrategyResult.of(stored, _STRATEGY_NEXT_STEP)

    @api.delete("/strategies/{strategy_id}")
    def remove_strategy(strategy_id: str) -> DeleteStrategyResult:
        delete_strategy(strategy_id, clock())
        return DeleteStrategyResult(strategy_id=strategy_id, deleted=True)

    @api.get("/strategies/{strategy_id}/preview")
    def preview(strategy_id: str, broker: Broker) -> StrategyPreviewResult:
        """The contracts each leg would trade now. Places nothing."""
        return StrategyPreviewResult.of(
            preview_strategy(strategy_id, get_adapter(broker), clock()), _PREVIEW_NEXT_STEP
        )

    @api.post("/strategies/{strategy_id}/start")
    def start(strategy_id: str, body: BrokerBody, key: ApiKey) -> StrategyCommandResult:
        """Enters the strategy now in the sandbox; openticker-serve watches it from then on."""
        command = control.request_start(strategy_id, body.broker, f"rest:{key.name}", clock())
        return StrategyCommandResult.of(command, False, _COMMAND_NEXT_STEP)

    @api.post("/strategies/{strategy_id}/stop")
    def stop(strategy_id: str, key: ApiKey) -> StrategyCommandResult:
        """Closes every open leg and ends the run."""
        command = control.request_stop(strategy_id, f"rest:{key.name}", clock())
        return StrategyCommandResult.of(command, False, _COMMAND_NEXT_STEP)

    @api.post("/strategies/{strategy_id}/kill")
    def kill(strategy_id: str, key: ApiKey) -> StrategyCommandResult:
        """Locks the strategy, then closes every open leg."""
        command = control.request_kill(strategy_id, f"rest:{key.name}", clock())
        return StrategyCommandResult.of(command, True, _COMMAND_NEXT_STEP)

    @api.post("/strategies/{strategy_id}/release")
    def release(strategy_id: str) -> StrategyResult:
        """Unlocks a killed strategy."""
        return StrategyResult.of(control.release_kill_switch(strategy_id))

    @api.post("/strategies/{strategy_id}/schedule")
    def schedule(strategy_id: str, body: BrokerBody) -> StrategyResult:
        """Enters the strategy at its entry_time on its weekdays, skipping holidays."""
        return StrategyResult.of(
            control.schedule_strategy(strategy_id, require_broker(body.broker))
        )

    @api.delete("/strategies/{strategy_id}/schedule")
    def unschedule(strategy_id: str) -> StrategyResult:
        """No more scheduled entries; a run already open carries on."""
        return StrategyResult.of(control.unschedule_strategy(strategy_id))

    @api.post("/strategies/{strategy_id}/legs/{leg_id}/close")
    def close_leg(strategy_id: str, leg_id: str, key: ApiKey) -> StrategyCommandResult:
        """Closes one leg; the run carries on with the others."""
        command = control.request_close_leg(strategy_id, leg_id, f"rest:{key.name}", clock())
        return StrategyCommandResult.of(command, False, _COMMAND_NEXT_STEP)

    @api.post("/signal-strategies")
    def new_signal_strategy(body: SignalStrategyBody) -> StrategyResult:
        """Saves a strategy alerts drive; places nothing."""
        stored = create_strategy(body.name, body.definition.to_spec(), clock())
        return StrategyResult.of(
            stored, "POST /api/v1/strategies/{strategy_id}/webhook gives it an alert URL."
        )

    @api.put("/signal-strategies/{strategy_id}")
    def change_signal_strategy(strategy_id: str, body: SignalStrategyBody) -> StrategyResult:
        return StrategyResult.of(
            update_strategy(strategy_id, body.name, body.definition.to_spec(), clock())
        )

    @api.post("/strategies/{strategy_id}/webhook")
    def rotate_webhook(strategy_id: str, body: WebhookBody) -> WebhookResult:
        """A new alert URL; the old one stops working. The token is shown only now."""
        stored, webhook, token = control.rotate_webhook(
            strategy_id, require_broker(body.broker), body.allowed_ips, clock()
        )
        return WebhookResult.of(
            stored, webhook, token, env.get("OPENTICKER_PUBLIC_URL"), ALERT_NEXT_STEP
        )

    @api.delete("/strategies/{strategy_id}/webhook")
    def disable_webhook(strategy_id: str) -> StrategyResult:
        return StrategyResult.of(control.disable_webhook(strategy_id))

    @api.get("/strategies/{strategy_id}/signals")
    def signals(
        strategy_id: str, limit: Annotated[int, Query(ge=1, le=100)] = 20
    ) -> StrategySignalsResult:
        return StrategySignalsResult.of(control.get_signals(strategy_id, limit))

    @api.get("/strategies/{strategy_id}/runs")
    def runs(
        strategy_id: str, limit: Annotated[int, Query(ge=1, le=100)] = 10
    ) -> StrategyRunsResult:
        return StrategyRunsResult.of(*control.get_runs(strategy_id, limit))

    @api.get("/runs/{run_id}")
    def run(run_id: str) -> StrategyRunResult:
        return StrategyRunResult.of_detail(control.get_run(run_id))

    @api.post("/scripts")
    def new_script(body: ScriptBody) -> ScriptResult:
        """Saves a Python script; runs nothing."""
        return ScriptResult.of_stored(
            scripts.upload_script(body.name, body.source, clock()),
            "POST /api/v1/scripts/{script_id}/start runs it.",
        )

    @api.get("/scripts")
    def all_scripts() -> ScriptsResult:
        return ScriptsResult(scripts=[ScriptResult.of(s) for s in scripts.list_scripts()])

    @api.get("/scripts/{script_id}")
    def script(
        script_id: str,
        runs: Annotated[int, Query(ge=1, le=50)] = 10,
        include_source: bool = False,
    ) -> ScriptDetailResult:
        return ScriptDetailResult.of(scripts.get_script(script_id, runs, include_source))

    @api.put("/scripts/{script_id}")
    def change_script(script_id: str, body: ScriptBody) -> ScriptResult:
        """Replaces the name and the whole source; refused while it runs."""
        return ScriptResult.of_stored(
            scripts.update_script(script_id, body.name, body.source, clock())
        )

    @api.delete("/scripts/{script_id}")
    def remove_script(script_id: str) -> DeleteScriptResult:
        scripts.delete_script(script_id)
        return DeleteScriptResult(script_id=script_id, deleted=True)

    @api.post("/scripts/{script_id}/start")
    def start_script(script_id: str, key: ApiKey) -> ScriptCommandResult:
        command = scripts.request_start(script_id, f"rest:{key.name}", clock())
        return ScriptCommandResult.of(command, _SCRIPT_COMMAND_NEXT_STEP)

    @api.post("/scripts/{script_id}/stop")
    def stop_script(script_id: str, key: ApiKey) -> ScriptCommandResult:
        command = scripts.request_stop(script_id, f"rest:{key.name}", clock())
        return ScriptCommandResult.of(command, _SCRIPT_COMMAND_NEXT_STEP)

    @api.post("/scripts/{script_id}/schedule")
    def schedule_script(script_id: str, body: ScriptScheduleDefinition) -> ScriptResult:
        return ScriptResult.of_stored(scripts.schedule_script(script_id, body.to_core()))

    @api.delete("/scripts/{script_id}/schedule")
    def unschedule_script(script_id: str) -> ScriptResult:
        return ScriptResult.of_stored(scripts.unschedule_script(script_id))

    @api.get("/scripts/{script_id}/logs")
    def script_logs(
        script_id: str,
        run_id: str | None = None,
        lines: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> ScriptLogsResult:
        return ScriptLogsResult.of(scripts.get_logs(script_id, run_id, lines))

    app.include_router(api)
    return app


def _responder(status: int) -> Callable[[Request, Exception], JSONResponse]:
    def respond(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return respond
