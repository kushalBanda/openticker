"""REST API: the MCP tools as HTTP routes, each a thin call into use_cases,
returning the same result shapes. Every route under /api/v1 needs an API key
in the `X-API-Key` header (ADR 17 in docs/adr), or a browser signed in to
the web app (ADR 31). A hosted script's key reaches
only prices, orders and positions (ADR 25). Signal strategies' alert URLs,
under /webhooks, are authenticated by the token in the URL instead (ADR 24).

Routes are plain `def`: FastAPI runs them on its thread pool, which keeps the
use cases sync (ADR 2 in docs/adr).
"""

import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from openticker.adapters.agents.harness import detect
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
    AgentJobLogResult,
    AgentJobResult,
    AgentJobsResult,
    AgentSettingsResult,
    AgentThreadResult,
    AgentThreadsResult,
    AgentThreadSummaryResult,
    AgentTurnResult,
    AlertResult,
    AuditLogResult,
    BarsResult,
    BasketResult,
    BrainFoundResult,
    BrainGraphResult,
    BrainNoteResult,
    BrainNotesResult,
    CancelAllResult,
    CancelOrderResult,
    ChargeCheckResult,
    ChargesResult,
    ChargesSummaryResult,
    CloseAllResult,
    ConnectResult,
    DayRecordResult,
    DebriefScheduleResult,
    DeleteScriptResult,
    DeleteStrategyResult,
    DeleteWatchlistResult,
    FolderCountResult,
    FolderSettingsResult,
    FundsResult,
    HarnessesResult,
    HarnessResult,
    HindsightInput,
    InstrumentRef,
    KeptYoursResult,
    LearningResult,
    LessonCheckedResult,
    LessonUseResult,
    LoginUrlResult,
    ManagerDayResult,
    ManagerDaysResult,
    ManagerLineInput,
    ManagerLineResult,
    ManagerNumbersResult,
    ManagerPlanResult,
    ManagerResult,
    MarginResult,
    MarketDepthResult,
    MarketStatusesResult,
    MarketStatusResult,
    ModifyOrderResult,
    MonthChargesResult,
    OptionChainResult,
    OrderbookEntryResult,
    OrderbookResult,
    OrderInput,
    PaperMarginResult,
    PayoffLegInput,
    PayoffResult,
    PlaceOrderResult,
    PnlHistoryResult,
    PositionsResult,
    QuoteResult,
    QuotesResult,
    RiskCheckResult,
    ScriptCommandResult,
    ScriptDetailResult,
    ScriptLimitsResult,
    ScriptLogsResult,
    ScriptResult,
    ScriptScheduleDefinition,
    ScriptsResult,
    SearchResult,
    SignalStrategyDefinition,
    StartDebriefResult,
    StartReviewResult,
    StrategiesResult,
    StrategyCommandResult,
    StrategyDefinition,
    StrategyLedgerResult,
    StrategyPreviewResult,
    StrategyResult,
    StrategyRunResult,
    StrategyRunsResult,
    StrategySignalsResult,
    StrategySummary,
    SyncResult,
    ThreadSearchResult,
    TradebookResult,
    TradeNoteInput,
    UndoneResult,
    WatchlistResult,
    WatchlistsResult,
    WebhookResult,
    closing_result,
)
from openticker.adapters.inbound.web.app import mount_web
from openticker.adapters.inbound.web.auth import (
    Caller,
    WebSettings,
    refuse_outside_scope,
    require_scope,
)
from openticker.adapters.inbound.web.stream import StreamHub
from openticker.composition import (
    AgentConfigError,
    SandboxConfigError,
    agent_settings,
    capital_cap,
    order_broker,
    sandbox_settings,
    script_limits,
)
from openticker.core.agents.choices import MAX_RUNS_PER_DAY, Effort, FolderKind, RunChoice
from openticker.core.agents.debriefs import DebriefScheduleError, parse_at
from openticker.core.agents.jobs import AgentSettings, Harness
from openticker.core.agents.manager import MAX_LINES_PER_CALL, ManagerError
from openticker.core.agents.threads import Access, Folder
from openticker.core.brain.lessons import (
    MAX_APPLIES_TO,
    MAX_EVIDENCE,
    CheckOutcome,
    Override,
    UsePurpose,
)
from openticker.core.brain.notes import (
    MAX_BODY,
    MAX_HINDSIGHT,
    MAX_LINE,
    MAX_TITLE,
    MAX_TRADE_NOTES,
    BrainNoteError,
    Debrief,
    NoteKind,
)
from openticker.core.brain.proposals import MAX_BASED_ON, Decision, Proposal
from openticker.core.calendar.calendar import CalendarError
from openticker.core.options.payoff import PayoffInputError
from openticker.core.options.underlyings import UnsupportedUnderlyingError
from openticker.core.orders.charges import ChargeBookError
from openticker.core.orders.models import OrderChanges, OrderRequest, OrderStatus, OrderType
from openticker.core.pnl import Source
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
from openticker.storage.sqlite.api_keys_repo import DuplicateApiKeyNameError
from openticker.storage.sqlite.brain_repo import StaleVersionError
from openticker.storage.sqlite.scripts_repo import DuplicateScriptNameError
from openticker.storage.sqlite.strategies_repo import DuplicateStrategyNameError
from openticker.storage.sqlite.watchlists_repo import (
    MAX_ITEMS,
    DuplicateWatchlistNameError,
    Watchlist,
    WatchlistLimitError,
)
from openticker.use_cases.agents import manage as agent_jobs
from openticker.use_cases.agents import manager as desk_manager
from openticker.use_cases.agents.manage import (
    MAX_AGENT_JOBS,
    AgentJobBusyError,
    AgentJobCapError,
    UnknownAgentJobError,
)
from openticker.use_cases.agents.settings import (
    AgentSettingsError,
    read_settings,
    reset_to_env,
    resolved_settings,
    set_folder_choice,
    set_harness,
    set_runs_per_day,
)
from openticker.use_cases.agents.threads import (
    ChatChoiceError,
    NothingToStopError,
    QueueFullError,
    SearchKind,
    ThreadBusyError,
    ThreadClosedError,
    TurnStartedError,
    UnknownThreadError,
    delete_thread,
    edit_queued,
    folder_counts,
    list_threads,
    pinned_threads,
    read_thread,
    remove_queued,
    search_threads,
    send_message,
    start_chat,
    stop_thread,
    thread_changes,
    update_thread,
)
from openticker.use_cases.api_keys import (
    InvalidApiKeyNameError,
    ManagedApiKeyError,
    UnknownApiKeyError,
)
from openticker.use_cases.brain import debrief as brain_debrief
from openticker.use_cases.brain import write as brain_write
from openticker.use_cases.brain.read import (
    MAX_LEARNING_DAYS,
    MAX_SEARCH,
    UnknownNoteError,
    Window,
    get_day_record,
    get_graph,
    get_learning,
    get_note,
    search_brain,
)
from openticker.use_cases.brain.write import edit_user_note, write_debrief
from openticker.use_cases.cancel_all_orders import cancel_all_orders
from openticker.use_cases.cancel_order import cancel_order
from openticker.use_cases.check_charge_rates import NoChargeSamplesError, check_charge_rates
from openticker.use_cases.close_all_positions import close_all_positions
from openticker.use_cases.close_position import NoOpenPositionError, close_position
from openticker.use_cases.connect_broker import connect_broker
from openticker.use_cases.errors import BatchTooLargeError, UnknownOrderError
from openticker.use_cases.evaluate_risk import evaluate_risk
from openticker.use_cases.get_audit_log import get_audit_log
from openticker.use_cases.get_funds import get_funds
from openticker.use_cases.get_historical_bars import get_historical_bars
from openticker.use_cases.get_margin import MAX_MARGIN_ORDERS, InvalidMarginOrderError, get_margin
from openticker.use_cases.get_market_depth import get_market_depth
from openticker.use_cases.get_market_status import get_market_status
from openticker.use_cases.get_option_chain import NoOptionsError, get_option_chain
from openticker.use_cases.get_order_status import get_order_status
from openticker.use_cases.get_orderbook import get_orderbook
from openticker.use_cases.get_positions import get_positions
from openticker.use_cases.get_quote import get_quote
from openticker.use_cases.get_quotes import MAX_QUOTES, get_quotes
from openticker.use_cases.get_tradebook import Period, get_tradebook, period_start, session_start
from openticker.use_cases.modify_order import modify_order
from openticker.use_cases.place_basket import MAX_BASKET, place_basket
from openticker.use_cases.place_order import place_order
from openticker.use_cases.placers import placer_names
from openticker.use_cases.pnl_history import (
    HistoryRangeError,
    get_charges_summary,
    get_pnl_history,
)
from openticker.use_cases.position_holders import holders
from openticker.use_cases.preview_charges import ChargesNotModelledError, preview_charges
from openticker.use_cases.preview_paper_margin import preview_paper_margin
from openticker.use_cases.preview_payoff import (
    MAX_PAYOFF_LEGS,
    MixedUnderlyingsError,
    preview_payoff,
)
from openticker.use_cases.reset_paper_account import ResetConfirmationError, ResetRefusedError
from openticker.use_cases.resolve_instrument import UnknownInstrumentError, resolve_instrument
from openticker.use_cases.scripts import manage as scripts
from openticker.use_cases.scripts.manage import (
    ScriptRunningError,
    ScriptStateError,
    UnknownScriptError,
)
from openticker.use_cases.search_instruments import search_instruments
from openticker.use_cases.strategies import control
from openticker.use_cases.strategies.board import strategy_board
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
    preview_strategy,
    update_strategy,
)
from openticker.use_cases.strategies.ledger import MAX_LEDGER_RUNS, get_strategy_ledger
from openticker.use_cases.strategies.signals import SignalResult, accept_signal
from openticker.use_cases.sync_instruments import sync_instruments
from openticker.use_cases.watchlists import (
    InvalidWatchlistNameError,
    UnknownWatchlistError,
    add_to_watchlist,
    create_watchlist,
    delete_watchlist,
    get_watchlists,
    instruments_of,
    remove_from_watchlist,
    rename_watchlist,
)

# The errors the MCP server turns into agent-facing messages (ADR 7 in docs/adr),
# here as HTTP statuses carrying the same message.
_ERROR_STATUSES: tuple[tuple[type[Exception], int], ...] = (
    (ManagerError, 422),
    (desk_manager.UnknownLineError, 404),
    (desk_manager.ManagerDayError, 404),
    (desk_manager.ManagerOffError, 409),
    (UnknownInstrumentError, 404),
    (UnknownBrokerError, 404),
    (UnsupportedUnderlyingError, 404),
    (NoOptionsError, 404),
    (UnknownOrderError, 404),
    (NoOpenPositionError, 404),
    (UnknownStrategyError, 404),
    (UnknownThreadError, 404),
    (ThreadBusyError, 409),
    (ThreadClosedError, 409),
    (QueueFullError, 409),
    (TurnStartedError, 409),
    (NothingToStopError, 409),
    (ChatChoiceError, 422),
    (AgentSettingsError, 422),
    (LegResolutionError, 404),
    (UnknownRunError, 404),
    (UnknownScriptError, 404),
    (UnknownApiKeyError, 404),
    (UnknownWatchlistError, 404),
    (UnknownNoteError, 404),
    (StaleVersionError, 409),
    (BrainNoteError, 422),
    (DebriefScheduleError, 422),
    (DuplicateWatchlistNameError, 409),
    (WatchlistLimitError, 409),
    (InvalidWatchlistNameError, 422),
    (DuplicateStrategyNameError, 409),
    (DuplicateApiKeyNameError, 409),
    (ManagedApiKeyError, 409),
    (ResetRefusedError, 409),
    (ResetConfirmationError, 422),
    (InvalidApiKeyNameError, 422),
    (StrategyRunningError, 409),
    (StrategyLockedError, 409),
    (StrategyStateError, 409),
    (StrategyKindError, 409),
    (DuplicateScriptNameError, 409),
    (ScriptRunningError, 409),
    (ScriptStateError, 409),
    (InvalidStrategyError, 422),
    (HistoryRangeError, 422),
    (InvalidScriptError, 422),
    (BatchTooLargeError, 422),
    (PayoffInputError, 422),
    (MixedUnderlyingsError, 422),
    (InvalidMarginOrderError, 422),
    (ChargesNotModelledError, 404),
    (NoChargeSamplesError, 404),
    (UnknownAgentJobError, 404),
    (AgentJobBusyError, 409),
    (AgentJobCapError, 429),
    (AgentConfigError, 503),
    (BrokerError, 502),
    (BrokerConfigError, 503),
    (SandboxConfigError, 503),
    (CalendarError, 503),
    (ChargeBookError, 503),
)

_NEXT_STEP = {
    OrderStatus.FILLED: "GET /api/v1/positions shows the position and its P&L.",
    OrderStatus.PENDING: "Rests until a live price crosses it; fills while openticker-serve "
    "runs. DELETE /api/v1/orders/{order_id} withdraws it.",
}

_CLOSE_NEXT_STEP = {
    OrderStatus.FILLED: "GET /api/v1/positions shows it flat; GET /api/v1/funds the realized P&L.",
}


def _close_next_step(status: OrderStatus) -> str:
    return _CLOSE_NEXT_STEP.get(status, "Fix what the reason says and close it again.")


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

Broker = Annotated[str, Query(description="Broker name, e.g. zerodha.")]
Symbol = Annotated[str, Query(description="Standardized symbol, e.g. RELIANCE, NIFTY 50.")]
ExchangeQuery = Annotated[Exchange, Query()]


class SendMessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=20_000, description="What you ask the agent.")
    model: str | None = Field(
        default=None, max_length=100, description="The model; left out, the harness's default."
    )
    effort: Effort | None = Field(default=None, description="How hard it thinks.")


class EditQueuedBody(BaseModel):
    message: str = Field(
        min_length=1, max_length=20_000, description="The waiting message, as it should read."
    )


class StartChatBody(SendMessageBody):
    folder: Folder = Folder.GENERAL
    access: Access = Field(
        default=Access.TRADE,
        description="read: the agent reads the desk and changes nothing; trade: it may also "
        "paper trade and change strategies. Fixed after the first message.",
    )
    subject: str | None = Field(
        default=None, description="The strategy's or script's id, for a chat about one."
    )
    harness: Harness | None = Field(
        default=None, description="claude or codex; left out, the folder's default."
    )


class UpdateThreadBody(BaseModel):
    """What the user changes about a chat; each field left out stays."""

    title: str | None = Field(default=None, min_length=1, max_length=80, description="Rename it.")
    pinned: bool | None = Field(default=None, description="Keep it on top of the list.")
    archived: bool | None = Field(
        default=None, description="Take it out of the list (true) or bring it back (false)."
    )
    read: bool | None = Field(default=None, description="true: the user has seen it.")


class FolderChoiceBody(BaseModel):
    """A folder kind's default; each field left out comes from the environment."""

    harness: Harness | None = None
    model: str | None = Field(default=None, max_length=100)
    effort: Effort | None = None
    max_budget_usd: float | None = Field(default=None, gt=0, le=1_000)
    timeout_minutes: int | None = Field(default=None, ge=1, le=24 * 60)


class AgentDefaultsBody(BaseModel):
    """Only the fields sent change; null puts one back to the environment."""

    harness: Harness | None = None
    runs_per_day: int | None = Field(default=None, ge=1, le=MAX_RUNS_PER_DAY)


class DebriefBody(BaseModel):
    headline: str = Field(max_length=MAX_LINE)
    happened: str = Field(max_length=MAX_BODY)
    trade_notes: list[TradeNoteInput] = Field(default=[], max_length=MAX_TRADE_NOTES)
    hindsight: list[HindsightInput] = Field(default=[], max_length=MAX_HINDSIGHT)


class UserNoteBody(BaseModel):
    text: str = Field(max_length=MAX_BODY, description="Markdown; blank clears it.")
    version: int = Field(description="The note's version the edit started from.")


class LessonBody(BaseModel):
    title: str = Field(max_length=MAX_TITLE)
    body: str = Field(max_length=MAX_BODY)
    applies_to: list[str] = Field(default=[], max_length=MAX_APPLIES_TO)
    evidence: list[str] = Field(default=[], max_length=MAX_EVIDENCE)


class LessonChangeBody(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TITLE)
    body: str | None = Field(default=None, max_length=MAX_BODY)
    applies_to: list[str] | None = Field(default=None, max_length=MAX_APPLIES_TO)


class LessonCheckBody(BaseModel):
    run_id: str | None = None
    order_id: str | None = None
    outcome: CheckOutcome
    observed: str | None = Field(default=None, max_length=MAX_LINE)
    why: str = Field(max_length=MAX_LINE)


class LessonUseBody(BaseModel):
    purpose: UsePurpose
    strategy_id: str | None = None
    how: str = Field(max_length=MAX_LINE)


class LessonOverrideBody(BaseModel):
    override: Literal["retired", "reinstated", "none"]
    reason: str | None = Field(default=None, max_length=MAX_LINE)


class ProposalBody(BaseModel):
    strategy_id: str
    change: str = Field(max_length=MAX_TITLE)
    why: str = Field(max_length=MAX_BODY)
    wrong_if: str = Field(max_length=MAX_LINE)
    based_on: list[str] = Field(default=[], max_length=MAX_BASED_ON)


class DecisionBody(BaseModel):
    decision: Decision
    reason: str | None = Field(default=None, max_length=MAX_LINE)


class StartDebriefBody(BaseModel):
    trading_date: date | None = Field(default=None, description="Omit: the latest closed day.")


class DebriefScheduleBody(BaseModel):
    at: str | None = Field(default=None, description="HH:MM, 15:40 or later; null: off.")


class ManagerSwitchBody(BaseModel):
    enabled: bool
    wakes_per_day: int | None = Field(default=None, ge=1, le=200)


class NextWakeBody(BaseModel):
    at: datetime = Field(description="Today, with its offset.")
    reason: str = Field(max_length=500)


class ManagerPlanBody(BaseModel):
    text: str = Field(max_length=4000)
    lesson_ids: list[str] = Field(default_factory=list, max_length=20)


class ManagerNumbersBody(BaseModel):
    lines: list[ManagerLineInput] = Field(min_length=1, max_length=MAX_LINES_PER_CALL)


class WatchlistNameBody(BaseModel):
    name: str = Field(description="1 to 40 characters, unique whatever its case.")


class WatchlistInstrumentsBody(BaseModel):
    instruments: list[InstrumentRef] = Field(min_length=1, max_length=MAX_ITEMS)


def _watchlist_result(watchlist: Watchlist) -> WatchlistResult:
    return WatchlistResult.of(watchlist, instruments_of(watchlist))


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


class QuotesBody(BaseModel):
    broker: str
    instruments: list[InstrumentRef] = Field(min_length=1, max_length=MAX_QUOTES)


class PayoffBody(BaseModel):
    broker: str
    legs: list[PayoffLegInput] = Field(min_length=1, max_length=MAX_PAYOFF_LEGS)


class MarginBody(BaseModel):
    broker: str
    orders: list[OrderInput] = Field(min_length=1, max_length=MAX_MARGIN_ORDERS)


class ClosePositionBody(BaseModel):
    broker: str
    symbol: str
    exchange: Exchange
    product: Product = Field(description="The position's product, as GET /positions shows it.")


class BasketBody(BaseModel):
    broker: str
    orders: list[OrderInput] = Field(min_length=1, max_length=MAX_BASKET)


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
    events: EventBus,
    env: Mapping[str, str],
    clock: Callable[[], datetime] = _utc_now,
    *,
    hub: StreamHub | None = None,
    web: WebSettings | None = None,
) -> FastAPI:
    """With `hub` and `web`, the web app too (ADR 30 in docs/adr); without,
    the REST API alone, for API keys only."""
    app = FastAPI(title="OpenTicker", version=version("openticker"))
    app.state.clock = clock
    app.state.web = web
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
    def connect(body: ConnectBody, caller: Caller) -> ConnectResult:
        connect_broker(get_adapter(body.broker), body.request_token, events, caller.triggered_by)
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
            today=clock().astimezone(EXCHANGE_TIMEZONE).date(),
            limit=limit + 1,
        )
        return SearchResult.of(found, limit)

    @api.get("/quote")
    def quote(broker: Broker, symbol: Symbol, exchange: ExchangeQuery) -> QuoteResult:
        return QuoteResult.of(get_quote(get_adapter(broker), symbol, exchange.value))

    @api.get("/depth")
    def depth(broker: Broker, symbol: Symbol, exchange: ExchangeQuery) -> MarketDepthResult:
        return MarketDepthResult.of(get_market_depth(get_adapter(broker), symbol, exchange.value))

    @api.post("/quotes")
    def quotes(body: QuotesBody) -> QuotesResult:
        """Quotes for up to 50 instruments; a read, POSTed because it takes a list."""
        wanted = [(item.symbol, item.exchange.value) for item in body.instruments]
        return QuotesResult.of(get_quotes(get_adapter(body.broker), wanted))

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
        now = clock()
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

    @api.post("/options/payoff")
    def options_payoff(body: PayoffBody) -> PayoffResult:
        """The payoff of up to 20 option and futures legs on one underlying, at
        expiry and today, with breakevens and the most it makes and loses.
        Nothing is placed."""
        return PayoffResult.of(
            preview_payoff(
                [leg.to_request() for leg in body.legs], get_adapter(body.broker), clock()
            )
        )

    @api.post("/orders")
    def create_order(body: PlaceOrderBody, caller: Caller) -> PlaceOrderResult:
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
            triggered_by=caller.triggered_by,
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

    @api.get("/charges/preview")
    def charges_preview(
        symbol: str,
        exchange: Exchange,
        side: Side,
        quantity: Annotated[int, Query(gt=0)],
        price: Annotated[float, Query(gt=0)],
        product: Product,
    ) -> ChargesResult:
        """What one paper fill of this order would pay in brokerage, taxes and
        fees, at the rates the sandbox charges."""
        return ChargesResult.of(preview_charges(symbol, exchange, side, quantity, price, product))

    @api.post("/charges/check")
    def charges_check(body: BrokerBody, caller: Caller) -> ChargeCheckResult:
        """Prices sample orders through the broker's contract note and compares
        them with the rates the sandbox charges. Nothing is placed."""
        return ChargeCheckResult.of(
            check_charge_rates(
                body.broker, get_adapter(body.broker), events, clock(), caller.triggered_by
            )
        )

    @api.post("/margin")
    def margin(body: MarginBody) -> MarginResult:
        """What the broker would block for these orders together, hedge benefit
        included. Nothing is placed."""
        return MarginResult.of(
            get_margin(get_adapter(body.broker), [o.to_order() for o in body.orders], clock())
        )

    @api.get("/margin/paper")
    def paper_margin(
        broker: Broker,
        symbol: Symbol,
        exchange: ExchangeQuery,
        side: Side,
        quantity: Annotated[int, Query(gt=0)],
        product: Product,
        price: Annotated[float, Query(gt=0)],
    ) -> PaperMarginResult:
        """What the paper account would block for this order, net of the
        position held, and the cash it has free. Nothing is placed."""
        return PaperMarginResult.of(
            preview_paper_margin(
                order_broker(broker, env, clock), symbol, exchange, side, quantity, product, price
            )
        )

    @api.post("/orders/basket")
    def create_basket(body: BasketBody, caller: Caller) -> BasketResult:
        """Up to 50 sandbox orders as one set, every BUY before any SELL. Not
        atomic: each order says its own status, and a refused one doesn't stop
        the rest."""
        placements = place_basket(
            [item.to_order() for item in body.orders],
            order_broker(body.broker, env, clock),
            events,
            capital_cap(env),
            load_calendar(),
            clock(),
            caller.triggered_by,
        )
        return BasketResult.of(
            placements,
            lambda status: _NEXT_STEP.get(
                status, "Fix what the reason says and place that order again."
            ),
        )

    @api.delete("/orders/{order_id}")
    def delete_order(order_id: str, broker: Broker, caller: Caller) -> CancelOrderResult:
        """Withdraws a PENDING order; anything else is left as it is."""
        result = cancel_order(
            order_id, order_broker(broker, env, clock), events, caller.triggered_by
        )
        return CancelOrderResult.of(order_id, result)

    @api.post("/orders/cancel-all")
    def cancel_all(body: BrokerBody, caller: Caller) -> CancelAllResult:
        """Withdraws every PENDING order, strategies' included. Strategies keep running."""
        return CancelAllResult.of(
            cancel_all_orders(order_broker(body.broker, env, clock), events, caller.triggered_by)
        )

    @api.post("/positions/close")
    def close_one(body: ClosePositionBody, caller: Caller) -> PlaceOrderResult:
        """Closes one position at the market for exactly what is held. A refusal
        (exchange closed, no fresh price) is a 200 with the reason."""
        position, result = close_position(
            order_broker(body.broker, env, clock),
            resolve_instrument(body.symbol, body.exchange.value),
            body.product,
            events,
            load_calendar(),
            clock(),
            caller.triggered_by,
        )
        return closing_result(position, result, _close_next_step)

    @api.post("/positions/close-all")
    def close_all(body: BrokerBody, caller: Caller) -> CloseAllResult:
        """Closes every open position at the market. Strategies are not stopped;
        pending orders stay (POST /orders/cancel-all withdraws them)."""
        closed = close_all_positions(
            order_broker(body.broker, env, clock),
            events,
            load_calendar(),
            clock(),
            caller.triggered_by,
        )
        return CloseAllResult.of(closed, _close_next_step)

    @api.patch("/orders/{order_id}")
    def patch_order(order_id: str, body: ModifyOrderBody, caller: Caller) -> ModifyOrderResult:
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
            caller.triggered_by,
        )
        return ModifyOrderResult.of(order_id, result, get_order_status(sandbox, order_id))

    @api.get("/market-status")
    def market_status(exchange: Exchange | None = None) -> MarketStatusesResult:
        exchanges = [exchange] if exchange is not None else list(Exchange)
        statuses = get_market_status(exchanges, clock())
        return MarketStatusesResult(exchanges=[MarketStatusResult.of(s) for s in statuses])

    @api.get("/orders")
    def orderbook(
        broker: Broker, limit: Annotated[int, Query(ge=1, le=200)] = 20, today_only: bool = False
    ) -> OrderbookResult:
        """Most recent first; `today_only`: placed on today's exchange-local date."""
        since = session_start(clock()) if today_only else None
        orders = get_orderbook(order_broker(broker, env, clock), limit, since)
        return OrderbookResult.of(orders, placer_names(o.triggered_by for o in orders))

    @api.get("/orders/{order_id}")
    def order_status(order_id: str, broker: Broker) -> OrderbookEntryResult:
        return OrderbookEntryResult.of(get_order_status(order_broker(broker, env, clock), order_id))

    @api.get("/trades")
    def tradebook(
        broker: Broker, limit: Annotated[int, Query(ge=1, le=500)] = 50, period: Period = "today"
    ) -> TradebookResult:
        """Fills since the start of today, this week or this month, newest first."""
        now = clock()
        trades = get_tradebook(order_broker(broker, env, clock), limit, now, period)
        return TradebookResult.of(
            trades, period_start(now, period), placer_names(t.triggered_by for t in trades)
        )

    @api.get("/pnl/history")
    def pnl_history(broker: Broker, from_date: date, to_date: date) -> PnlHistoryResult:
        """The paper account's P&L by trading day, after charges; today live."""
        return PnlHistoryResult.of(
            get_pnl_history(
                from_date, to_date, order_broker(broker, env, clock), load_calendar(), clock()
            )
        )

    @api.get("/charges/summary")
    def charges_summary(from_date: date, to_date: date) -> ChargesSummaryResult:
        """Charges paid by paper fills, month by month and by charge."""
        months = get_charges_summary(from_date, to_date)
        return ChargesSummaryResult(
            months=[MonthChargesResult.of(m) for m in months],
            total=round(sum(m.total for m in months), 2),
        )

    @api.get("/brain/graph")
    def brain_graph(window: Window = "30") -> BrainGraphResult:
        """The brain's notes in a window of trading days and the links among them."""
        return BrainGraphResult.of(get_graph(window, clock(), load_calendar()))

    @api.get("/brain/notes")
    def brain_notes(
        query: Annotated[str | None, Query(max_length=200)] = None,
        kind: NoteKind | None = None,
        status: str | None = None,
        strategy_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_SEARCH)] = 20,
    ) -> BrainNotesResult:
        """Notes by text, kind, status or strategy, newest first."""
        found = search_brain(query, kind, status, strategy_id, limit, clock())
        return BrainNotesResult(notes=[BrainFoundResult.of(f) for f in found])

    @api.get("/brain/notes/{note_id}")
    def brain_note(note_id: str) -> BrainNoteResult:
        """One note with its links, backlinks and the facts it cites."""
        return BrainNoteResult.of_view(get_note(note_id))

    @api.get("/brain/days/{trading_date}/record")
    def day_record(trading_date: date, broker: Broker) -> DayRecordResult:
        """One trading day: P&L, trades by run or order, owed checks, the debrief's words."""
        record = get_day_record(
            trading_date, order_broker(broker, env, clock), clock(), load_calendar()
        )
        return DayRecordResult.of(record, placer_names(t.triggered_by for t in record.trades))

    @api.put("/brain/days/{trading_date}")
    def debrief(trading_date: date, body: DebriefBody, caller: Caller) -> BrainNoteResult:
        """Writes the day's debrief; again replaces it. The user's note is kept."""
        written = write_debrief(
            Debrief(
                trading_date,
                body.headline,
                body.happened,
                tuple(n.to_core() for n in body.trade_notes),
                tuple(h.to_core() for h in body.hindsight),
            ),
            events,
            clock(),
            load_calendar(),
            caller.triggered_by,
        )
        return BrainNoteResult.of_view(written)

    @api.patch("/brain/notes/{note_id}")
    def edit_note(note_id: str, body: UserNoteBody, caller: Caller) -> BrainNoteResult:
        """The user's own part of a note. 409 when the note changed since `version`."""
        return BrainNoteResult.of_view(
            edit_user_note(note_id, body.text, body.version, events, clock(), caller.triggered_by)
        )

    @api.post("/brain/lessons")
    def new_lesson(body: LessonBody, caller: Caller) -> BrainNoteResult:
        """A new lesson; a hunch until its checks say more."""
        return BrainNoteResult.of_view(
            brain_write.create_lesson(
                body.title,
                body.body,
                body.applies_to,
                body.evidence,
                events,
                clock(),
                caller.triggered_by,
            )
        )

    @api.patch("/brain/lessons/{lesson_id}")
    def change_lesson(lesson_id: str, body: LessonChangeBody, caller: Caller) -> BrainNoteResult:
        """A lesson's title, text or strategies; omitted ones stay."""
        return BrainNoteResult.of_view(
            brain_write.update_lesson(
                lesson_id,
                body.title,
                body.body,
                body.applies_to,
                events,
                clock(),
                caller.triggered_by,
            )
        )

    @api.post("/brain/lessons/{lesson_id}/checks")
    def lesson_check(lesson_id: str, body: LessonCheckBody, caller: Caller) -> LessonCheckedResult:
        """Whether the lesson held on an ended run or an order outside a strategy."""
        refuse_outside_scope(
            caller, "check_lesson", {"run_id": body.run_id, "order_id": body.order_id}
        )
        view, check, replaced = brain_write.check_lesson(
            lesson_id,
            body.run_id,
            body.order_id,
            body.outcome,
            body.observed,
            body.why,
            events,
            clock(),
            caller.triggered_by,
        )
        return LessonCheckedResult.of(view, check, replaced)

    @api.post("/brain/lessons/{lesson_id}/uses")
    def lesson_use(lesson_id: str, body: LessonUseBody, caller: Caller) -> LessonUseResult:
        """That a lesson was relied on, and for what."""
        refuse_outside_scope(caller, "record_lesson_use", {"strategy_id": body.strategy_id})
        return LessonUseResult.of(
            brain_write.record_lesson_use(
                lesson_id,
                body.purpose,
                body.strategy_id,
                body.how,
                None,
                clock(),
                caller.triggered_by,
            )
        )

    @api.post("/brain/lessons/{lesson_id}/override")
    def lesson_override(
        lesson_id: str, body: LessonOverrideBody, caller: Caller
    ) -> BrainNoteResult:
        """Retire a lesson (with a reason), reinstate it, or clear either."""
        return BrainNoteResult.of_view(
            brain_write.set_lesson_override(
                lesson_id,
                None if body.override == "none" else Override(body.override),
                body.reason,
                events,
                clock(),
                caller.triggered_by,
            )
        )

    @api.post("/brain/proposals")
    def new_proposal(body: ProposalBody, caller: Caller) -> BrainNoteResult:
        """One change to one strategy, for the user to decide."""
        refuse_outside_scope(caller, "raise_proposal", {"strategy_id": body.strategy_id})
        return BrainNoteResult.of_view(
            brain_write.raise_proposal(
                Proposal(
                    body.strategy_id, body.change, body.why, body.wrong_if, tuple(body.based_on)
                ),
                events,
                clock(),
                caller.triggered_by,
            )
        )

    @api.post("/brain/proposals/{proposal_id}/decision")
    def proposal_decision(proposal_id: str, body: DecisionBody, caller: Caller) -> BrainNoteResult:
        """Accept, reject with a reason, or later. Accept and reject are final."""
        return BrainNoteResult.of_view(
            brain_write.decide_proposal(
                proposal_id, body.decision, body.reason, events, clock(), caller.triggered_by
            )
        )

    @api.post("/brain/debrief")
    def debrief_now(body: StartDebriefBody, caller: Caller) -> StartDebriefResult:
        """Asks openticker-serve to debrief a day now with the user's coding agent."""
        job = brain_debrief.start_debrief(
            body.trading_date,
            resolved_settings(agent_settings(env)),
            caller.triggered_by,
            clock(),
            load_calendar(),
        )
        return StartDebriefResult(job=AgentJobResult.of(job, {}))

    @api.put("/brain/debrief-schedule")
    def set_debrief_schedule(body: DebriefScheduleBody) -> DebriefScheduleResult:
        """The daily debrief's time after the close, or off."""
        schedule = parse_at(body.at) if body.at else None
        return DebriefScheduleResult.of(
            *brain_debrief.schedule_debrief(schedule, clock(), load_calendar())
        )

    @api.get("/brain/learning")
    def learning(
        days: Annotated[int, Query(ge=1, le=MAX_LEARNING_DAYS)] = 30,
    ) -> LearningResult:
        """Whether the brain is being read: designs and reviews citing a
        lesson, checks given and owed, lessons that held."""
        return LearningResult.of(get_learning(days, clock()))

    @api.get("/brain/debrief-schedule")
    def debrief_schedule() -> DebriefScheduleResult:
        """When the daily debrief runs, and when it's next due."""
        return DebriefScheduleResult.of(
            *brain_debrief.get_debrief_schedule(clock(), load_calendar())
        )

    @api.get("/manager")
    def manager() -> ManagerResult:
        """The desk manager: on or off, its next look, its plan and its lines."""
        return ManagerResult.of(
            desk_manager.get_manager(
                sandbox_settings(env).starting_capital, load_calendar(), clock()
            )
        )

    @api.get("/manager/days")
    def manager_days(start: date, end: date | None = None) -> ManagerDaysResult:
        """Every trading day from start to end, with whether the manager ran."""
        now = clock()
        return ManagerDaysResult.of(
            desk_manager.list_manager_days(
                start, end or now.astimezone(EXCHANGE_TIMEZONE).date(), load_calendar(), now
            )
        )

    @api.get("/manager/days/{trading_date}")
    def manager_day(trading_date: date) -> ManagerDayResult:
        """One trading day of the manager's, read back: today live, a past day as it closed."""
        return ManagerDayResult.of(
            desk_manager.get_manager_day(trading_date, load_calendar(), clock())
        )

    @api.put("/manager")
    def set_manager(body: ManagerSwitchBody, caller: Caller) -> ManagerResult:
        """Turns the desk manager on or off."""
        desk_manager.set_manager(
            body.enabled, body.wakes_per_day, events, caller.triggered_by, clock()
        )
        return manager()

    @api.post("/manager/wake")
    def wake_manager(caller: Caller) -> AgentJobResult:
        """Look now: the manager takes a turn at once."""
        return AgentJobResult.of(
            desk_manager.wake_manager(
                resolved_settings(agent_settings(env)), events, caller.triggered_by, clock()
            ),
            {},
        )

    @api.put("/manager/next-wake")
    def set_next_wake(body: NextWakeBody) -> ManagerResult:
        """When the manager looks next, today."""
        desk_manager.set_next_wake(body.at, body.reason, load_calendar(), clock())
        return manager()

    @api.put("/manager/plan")
    def set_manager_plan(body: ManagerPlanBody, caller: Caller) -> ManagerPlanResult:
        """Today's plan, with the lessons it relied on."""
        return ManagerPlanResult.of(
            desk_manager.set_plan(body.text, body.lesson_ids, events, caller.triggered_by, clock())
        )

    @api.put("/manager/numbers")
    def set_manager_numbers(body: ManagerNumbersBody, caller: Caller) -> ManagerNumbersResult:
        """Lines' capital and stop. From the web app or a full key, the user's:
        they stand over the manager's."""
        views, kept, left = desk_manager.set_manager_numbers(
            [desk_manager.LineChange(l.key, l.capital, l.stop, l.reason) for l in body.lines],
            events,
            caller.triggered_by,
            load_calendar(),
            clock(),
        )
        return ManagerNumbersResult(
            lines=[ManagerLineResult.of(v) for v in views],
            kept_yours=[KeptYoursResult.of(k) for k in kept],
            undone=[UndoneResult.of(u) for u in left],
        )

    @api.delete("/manager/numbers/{key}/override")
    def clear_manager_override(key: str, caller: Caller) -> ManagerLineResult:
        """Hands a line the user set back to the manager."""
        return ManagerLineResult.of(
            desk_manager.clear_override(key, events, caller.triggered_by, load_calendar(), clock())
        )

    @api.get("/watchlists")
    def watchlists() -> WatchlistsResult:
        """Every watchlist with its instruments, in the order they were made."""
        return WatchlistsResult(watchlists=[_watchlist_result(w) for w in get_watchlists()])

    @api.post("/watchlists")
    def new_watchlist(body: WatchlistNameBody, caller: Caller) -> WatchlistResult:
        """A new, empty list. At most 20."""
        return _watchlist_result(create_watchlist(body.name, events, clock(), caller.triggered_by))

    @api.patch("/watchlists/{watchlist_id}")
    def rename(watchlist_id: str, body: WatchlistNameBody, caller: Caller) -> WatchlistResult:
        return _watchlist_result(
            rename_watchlist(watchlist_id, body.name, events, clock(), caller.triggered_by)
        )

    @api.delete("/watchlists/{watchlist_id}")
    def remove_watchlist(watchlist_id: str, caller: Caller) -> DeleteWatchlistResult:
        gone = delete_watchlist(watchlist_id, events, clock(), caller.triggered_by)
        return DeleteWatchlistResult(watchlist_id=gone.watchlist_id, name=gone.name, deleted=True)

    @api.post("/watchlists/{watchlist_id}/instruments")
    def watch(watchlist_id: str, body: WatchlistInstrumentsBody, caller: Caller) -> WatchlistResult:
        """Adds to the end of the list; one already on it stays where it is. At most 50."""
        wanted = [(i.symbol, i.exchange.value) for i in body.instruments]
        return _watchlist_result(
            add_to_watchlist(watchlist_id, wanted, events, clock(), caller.triggered_by)
        )

    @api.delete("/watchlists/{watchlist_id}/instruments")
    def unwatch(
        watchlist_id: str, body: WatchlistInstrumentsBody, caller: Caller
    ) -> WatchlistResult:
        """Takes instruments off the list; one not on it is ignored."""
        unwanted = [(i.symbol, i.exchange.value) for i in body.instruments]
        return _watchlist_result(
            remove_from_watchlist(watchlist_id, unwanted, events, clock(), caller.triggered_by)
        )

    @api.get("/positions")
    def positions(broker: Broker, include_closed: bool = False) -> PositionsResult:
        """Each with the running strategies holding part of it."""
        marks = hub.marks() if hub is not None else None
        held = get_positions(order_broker(broker, env, clock, marks))
        return PositionsResult.of(held, include_closed, holders(held))

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
        event_type: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
        event_types: Annotated[list[str] | None, Query()] = None,
        source: Source | None = None,
        from_date: date | None = None,
        before_id: Annotated[int | None, Query(ge=1)] = None,
    ) -> AuditLogResult:
        return AuditLogResult.of(
            get_audit_log(
                limit,
                event_type,
                event_types=event_types or (),
                source=source,
                from_date=from_date,
                before_id=before_id,
            )
        )

    @api.post("/strategies")
    def new_strategy(body: StrategyBody, caller: Caller) -> StrategyResult:
        """Saves a definition. Places nothing."""
        stored = create_strategy(body.name, body.definition.to_spec(), clock(), caller.triggered_by)
        return StrategyResult.of(stored, _STRATEGY_NEXT_STEP)

    @api.get("/strategies")
    def strategies() -> StrategiesResult:
        return StrategiesResult(
            strategies=[StrategySummary.of(row) for row in strategy_board(load_calendar(), clock())]
        )

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
    def start(strategy_id: str, body: BrokerBody, caller: Caller) -> StrategyCommandResult:
        """Enters the strategy now in the sandbox; openticker-serve watches it from then on."""
        command = control.request_start(strategy_id, body.broker, caller.triggered_by, clock())
        return StrategyCommandResult.of(command, False, _COMMAND_NEXT_STEP)

    @api.post("/strategies/{strategy_id}/stop")
    def stop(strategy_id: str, caller: Caller) -> StrategyCommandResult:
        """Closes every open leg and ends the run."""
        command = control.request_stop(strategy_id, caller.triggered_by, clock())
        return StrategyCommandResult.of(command, False, _COMMAND_NEXT_STEP)

    @api.post("/strategies/{strategy_id}/kill")
    def kill(strategy_id: str, caller: Caller) -> StrategyCommandResult:
        """Locks the strategy, then closes every open leg."""
        command = control.request_kill(strategy_id, caller.triggered_by, clock())
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
    def close_leg(strategy_id: str, leg_id: str, caller: Caller) -> StrategyCommandResult:
        """Closes one leg; the run carries on with the others."""
        command = control.request_close_leg(strategy_id, leg_id, caller.triggered_by, clock())
        return StrategyCommandResult.of(command, False, _COMMAND_NEXT_STEP)

    @api.post("/signal-strategies")
    def new_signal_strategy(body: SignalStrategyBody, caller: Caller) -> StrategyResult:
        """Saves a strategy alerts drive; places nothing."""
        stored = create_strategy(body.name, body.definition.to_spec(), clock(), caller.triggered_by)
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

    @api.get("/strategies/{strategy_id}/ledger")
    def ledger(
        strategy_id: str, limit: Annotated[int, Query(ge=1, le=MAX_LEDGER_RUNS)] = 20
    ) -> StrategyLedgerResult:
        """Totals over every run after costs, and the newest runs with their fills."""
        return StrategyLedgerResult.of(get_strategy_ledger(strategy_id, limit))

    @api.post("/strategies/{strategy_id}/review")
    def review(strategy_id: str, caller: Caller) -> StartReviewResult:
        """Asks openticker-serve to review the strategy now with the user's coding agent."""
        job = agent_jobs.start_review(
            strategy_id, resolved_settings(agent_settings(env)), caller.triggered_by, clock()
        )
        return StartReviewResult(job=AgentJobResult.of(job, agent_jobs.strategy_names()))

    @api.get("/agent-jobs")
    def jobs(
        strategy_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_AGENT_JOBS)] = 10,
    ) -> AgentJobsResult:
        """Agent jobs, newest first."""
        found = agent_jobs.get_agent_jobs(limit, strategy_id)
        names = agent_jobs.strategy_names()
        return AgentJobsResult(jobs=[AgentJobResult.of(job, names) for job in found])

    @api.get("/agent-jobs/{job_id}/log")
    def job_log(job_id: str) -> AgentJobLogResult:
        """The end of what an agent job printed."""
        return AgentJobLogResult.of(agent_jobs.get_agent_job_log(job_id))

    @api.post("/agent-jobs/{job_id}/stop")
    def stop_job(job_id: str, caller: Caller) -> AgentJobResult:
        """Ends a waiting job at once; asks a running one to stop."""
        return AgentJobResult.of(
            agent_jobs.stop_agent_job(job_id, events, caller.triggered_by, clock()),
            agent_jobs.strategy_names(),
        )

    def resolved() -> AgentSettings:
        return resolved_settings(agent_settings(env))

    @api.get("/agents/settings")
    def get_agent_settings() -> AgentSettingsResult:
        """How the user's coding agent runs: each folder's default, from Settings
        and the environment (ADR 40)."""
        return AgentSettingsResult.of(read_settings(agent_settings(env)))

    @api.patch("/agents/settings")
    def change_agent_defaults(body: AgentDefaultsBody, caller: Caller) -> AgentSettingsResult:
        """The harness every folder uses, and the background runs a day."""
        if "harness" in body.model_fields_set:
            set_harness(body.harness, caller.triggered_by, events, clock())
        if "runs_per_day" in body.model_fields_set:
            set_runs_per_day(body.runs_per_day, caller.triggered_by, events, clock())
        return AgentSettingsResult.of(read_settings(agent_settings(env)))

    @api.put("/agents/settings/folders/{kind}")
    def change_folder_choice(
        kind: FolderKind, body: FolderChoiceBody, caller: Caller
    ) -> FolderSettingsResult:
        """Replaces a folder kind's default."""
        choice = RunChoice(
            harness=body.harness,
            model=(body.model or "").strip() or None,
            effort=body.effort,
            max_budget_usd=body.max_budget_usd,
            timeout=timedelta(minutes=body.timeout_minutes) if body.timeout_minutes else None,
        )
        return FolderSettingsResult.of(
            set_folder_choice(
                kind, choice, agent_settings(env), caller.triggered_by, events, clock()
            )
        )

    @api.delete("/agents/settings")
    def reset_agent_settings(caller: Caller) -> AgentSettingsResult:
        """Every agent setting back to the environment."""
        reset_to_env(caller.triggered_by, events, clock())
        return AgentSettingsResult.of(read_settings(agent_settings(env)))

    @api.get("/agents/harnesses")
    def harnesses() -> HarnessesResult:
        """Which coding agents are on this machine, with their models and efforts."""
        return HarnessesResult(harnesses=[HarnessResult.of(info) for info in detect(env)])

    @api.get("/agent-threads")
    def threads(
        folder: Folder | None = None,
        subject: Annotated[str | None, Query(max_length=64)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> AgentThreadsResult:
        """The web app's chats with the user's coding agent, most recent first
        (ADR 40), in one folder when asked (a strategy's holds its reviews),
        and how many each folder holds."""
        names = agent_jobs.strategy_names()
        return AgentThreadsResult(
            threads=[
                AgentThreadResult.of(view, names).summary()
                for view in list_threads(folder, subject, limit)
            ],
            pinned=[
                AgentThreadResult.of(view, names).summary()
                for view in (pinned_threads() if folder is None else [])
            ],
            counts=[FolderCountResult.of(count) for count in folder_counts()],
        )

    @api.post("/agent-threads", status_code=202)
    def new_thread(body: StartChatBody, caller: Caller) -> AgentThreadResult:
        """Starts a chat; its first message runs as an agent job."""
        view = start_chat(
            body.folder,
            body.subject,
            body.message,
            body.model,
            body.effort,
            resolved(),
            caller.triggered_by,
            clock(),
            harness=body.harness,
            events=events,
            access=body.access,
        )
        return AgentThreadResult.of(view, agent_jobs.strategy_names())

    @api.get("/agent-threads/search")
    def search_chats(
        q: Annotated[str, Query(min_length=2, max_length=100, description="Words to find.")],
        kind: SearchKind | None = None,
        archived: bool = False,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> ThreadSearchResult:
        """Chats, reviews and debriefs whose title, messages or answers hold
        the words; the archived ones only with archived=true."""
        found = search_threads(q, kind, archived, limit)
        return ThreadSearchResult.of(found, agent_jobs.strategy_names())

    @api.get("/agent-threads/{thread_id}")
    def thread(thread_id: str) -> AgentThreadResult:
        """One chat with every turn and its steps."""
        return AgentThreadResult.of(read_thread(thread_id), agent_jobs.strategy_names())

    @api.patch("/agent-threads/{thread_id}")
    def change_thread(thread_id: str, body: UpdateThreadBody) -> AgentThreadSummaryResult:
        """Renames, pins, archives or marks a chat read."""
        update_thread(
            thread_id,
            clock(),
            title=body.title,
            pinned=body.pinned,
            archived=body.archived,
            read=body.read,
        )
        return AgentThreadResult.of(read_thread(thread_id), agent_jobs.strategy_names()).summary()

    @api.get("/agent-threads/{thread_id}/changes")
    def chat_changes(
        thread_id: str, job_id: Annotated[str | None, Query(max_length=64)] = None
    ) -> AuditLogResult:
        """What the agent changed on the desk from this chat, in one turn when
        asked: the audit entries recorded as the chat, most recent first."""
        return AuditLogResult.of(thread_changes(thread_id, job_id))

    @api.delete("/agent-threads/{thread_id}", status_code=204)
    def remove_thread(thread_id: str, caller: Caller) -> None:
        """Deletes a chat from the web app; its turns stay as agent jobs."""
        delete_thread(thread_id, events, caller.triggered_by, clock())

    @api.post("/agent-threads/{thread_id}/messages", status_code=202)
    def send(thread_id: str, body: SendMessageBody, caller: Caller) -> AgentTurnResult:
        """Sends a message to a chat; the agent's reply runs as an agent job. Sent
        while the agent works, it waits its turn; 409 when one already waits."""
        turn = send_message(
            thread_id,
            body.message,
            body.model,
            body.effort,
            resolved(),
            caller.triggered_by,
            clock(),
        )
        return AgentTurnResult.of(turn, agent_jobs.strategy_names())

    @api.patch("/agent-threads/{thread_id}/messages/{job_id}")
    def edit_waiting(thread_id: str, job_id: str, body: EditQueuedBody) -> AgentTurnResult:
        """Rewrites the message waiting for the agent; 409 once the agent took it."""
        turn = edit_queued(thread_id, job_id, body.message)
        return AgentTurnResult.of(turn, agent_jobs.strategy_names())

    @api.delete("/agent-threads/{thread_id}/messages/{job_id}")
    def remove_waiting(thread_id: str, job_id: str, caller: Caller) -> AgentJobResult:
        """Takes back the message waiting for the agent; 409 once the agent took it."""
        job = remove_queued(thread_id, job_id, events, caller.triggered_by, clock())
        return AgentJobResult.of(job, agent_jobs.strategy_names())

    @api.post("/agent-threads/{thread_id}/stop")
    def stop_thread_turn(thread_id: str, caller: Caller) -> AgentJobResult:
        """Stops the turn the agent is on; a message waiting behind it still runs."""
        job = stop_thread(thread_id, events, caller.triggered_by, clock())
        return AgentJobResult.of(job, agent_jobs.strategy_names())

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
        return ScriptsResult(
            scripts=[ScriptResult.of(s) for s in scripts.list_scripts()],
            limits=ScriptLimitsResult.of(script_limits(env)),
        )

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
    def start_script(script_id: str, caller: Caller) -> ScriptCommandResult:
        command = scripts.request_start(script_id, caller.triggered_by, clock())
        return ScriptCommandResult.of(command, _SCRIPT_COMMAND_NEXT_STEP)

    @api.post("/scripts/{script_id}/stop")
    def stop_script(script_id: str, caller: Caller) -> ScriptCommandResult:
        command = scripts.request_stop(script_id, caller.triggered_by, clock())
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
    if hub is not None and web is not None:
        mount_web(app, events=events, env=env, hub=hub, web=web, clock=clock)
    return app


def _responder(status: int) -> Callable[[Request, Exception], JSONResponse]:
    def respond(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return respond
