"""REST API: the MCP tools as HTTP routes, each a thin call into use_cases,
returning the same result shapes. Every route under /api/v1 needs an API key
in the `X-API-Key` header (ADR 17 in docs/adr).

Routes are plain `def`: FastAPI runs them on its thread pool, which keeps the
use cases sync (ADR 2 in docs/adr).
"""

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
)
from openticker.adapters.inbound.mcp_models import (
    AuditLogResult,
    BarsResult,
    CancelOrderResult,
    ConnectResult,
    DeleteStrategyResult,
    FundsResult,
    LoginUrlResult,
    MarketStatusesResult,
    MarketStatusResult,
    OptionChainResult,
    OrderbookResult,
    PlaceOrderResult,
    PositionsResult,
    QuoteResult,
    RiskCheckResult,
    SearchResult,
    StrategiesResult,
    StrategyCommandResult,
    StrategyDefinition,
    StrategyPreviewResult,
    StrategyResult,
    StrategyRunResult,
    StrategyRunsResult,
    StrategySummary,
    SyncResult,
)
from openticker.composition import SandboxConfigError, capital_cap, order_broker
from openticker.core.calendar.calendar import CalendarError
from openticker.core.options.underlyings import UnsupportedUnderlyingError
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
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
from openticker.storage.sqlite.strategies_repo import DuplicateStrategyNameError
from openticker.use_cases.api_keys import authenticate
from openticker.use_cases.cancel_order import UnknownOrderError, cancel_order
from openticker.use_cases.connect_broker import connect_broker
from openticker.use_cases.evaluate_risk import evaluate_risk
from openticker.use_cases.get_audit_log import get_audit_log
from openticker.use_cases.get_funds import get_funds
from openticker.use_cases.get_historical_bars import get_historical_bars
from openticker.use_cases.get_market_status import get_market_status
from openticker.use_cases.get_option_chain import NoOptionsError, get_option_chain
from openticker.use_cases.get_orderbook import get_orderbook
from openticker.use_cases.get_positions import get_positions
from openticker.use_cases.get_quote import get_quote
from openticker.use_cases.place_order import place_order
from openticker.use_cases.resolve_instrument import UnknownInstrumentError, resolve_instrument
from openticker.use_cases.search_instruments import search_instruments
from openticker.use_cases.strategies import control
from openticker.use_cases.strategies.control import (
    StrategyLockedError,
    StrategyStateError,
    UnknownRunError,
)
from openticker.use_cases.strategies.define import (
    StrategyRunningError,
    UnknownStrategyError,
    create_strategy,
    delete_strategy,
    get_strategy,
    list_strategies,
    preview_strategy,
    update_strategy,
)
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
    (DuplicateStrategyNameError, 409),
    (StrategyRunningError, 409),
    (StrategyLockedError, 409),
    (StrategyStateError, 409),
    (InvalidStrategyError, 422),
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

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

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
            triggered_by=f"rest:{key.name}",
        )
        result = place_order(
            request,
            order_broker(body.broker, env),
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
        result = cancel_order(order_id, order_broker(broker, env), events, f"rest:{key.name}")
        return CancelOrderResult.of(order_id, result)

    @api.get("/market-status")
    def market_status(exchange: Exchange | None = None) -> MarketStatusesResult:
        exchanges = [exchange] if exchange is not None else list(Exchange)
        statuses = get_market_status(exchanges, clock())
        return MarketStatusesResult(exchanges=[MarketStatusResult.of(s) for s in statuses])

    @api.get("/orders")
    def orderbook(
        broker: Broker, limit: Annotated[int, Query(ge=1, le=200)] = 20
    ) -> OrderbookResult:
        return OrderbookResult.of(get_orderbook(order_broker(broker, env), limit))

    @api.get("/positions")
    def positions(broker: Broker, include_closed: bool = False) -> PositionsResult:
        return PositionsResult.of(get_positions(order_broker(broker, env)), include_closed)

    @api.get("/funds")
    def funds(broker: Broker) -> FundsResult:
        return FundsResult.of(get_funds(order_broker(broker, env)))

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

    @api.post("/strategies/{strategy_id}/legs/{leg_id}/close")
    def close_leg(strategy_id: str, leg_id: str, key: ApiKey) -> StrategyCommandResult:
        """Closes one leg; the run carries on with the others."""
        command = control.request_close_leg(strategy_id, leg_id, f"rest:{key.name}", clock())
        return StrategyCommandResult.of(command, False, _COMMAND_NEXT_STEP)

    @api.get("/strategies/{strategy_id}/runs")
    def runs(
        strategy_id: str, limit: Annotated[int, Query(ge=1, le=100)] = 10
    ) -> StrategyRunsResult:
        return StrategyRunsResult.of(*control.get_runs(strategy_id, limit))

    @api.get("/runs/{run_id}")
    def run(run_id: str) -> StrategyRunResult:
        return StrategyRunResult.of_detail(control.get_run(run_id))

    app.include_router(api)
    return app


def _responder(status: int) -> Callable[[Request, Exception], JSONResponse]:
    def respond(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return respond
