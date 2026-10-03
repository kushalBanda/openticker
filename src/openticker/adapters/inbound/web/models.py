"""Results of the web app's own routes, and the stream's messages (ADR 31 and
ADR 32 in docs/adr). Times go out exchange-local, like every other result."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from openticker.adapters.inbound.mcp_models import AuditEntryResult, InstrumentRef
from openticker.adapters.sandbox.broker import SandboxSettings
from openticker.core.agents.jobs import AgentSettings, Harness
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange, Tick
from openticker.storage.sqlite.agent_clients_repo import AgentClient
from openticker.storage.sqlite.api_keys_repo import StoredApiKey
from openticker.storage.sqlite.web_repo import WebSession
from openticker.use_cases.api_keys import FULL_SCOPE
from openticker.use_cases.feed_status import FeedState, FeedStatus
from openticker.use_cases.settings_state import BrokerSession, ChargeRates, InstrumentStatus
from openticker.use_cases.setup_state import SetupState
from openticker.use_cases.today import Today

MAX_SUBSCRIPTIONS = 200  # per connection


def _local(moment: datetime | None) -> datetime | None:
    return moment.astimezone(EXCHANGE_TIMEZONE) if moment is not None else None


class SessionResult(BaseModel):
    signed_in_at: datetime
    expires_at: datetime
    visit_started_at: datetime | None
    previous_visit_at: datetime | None

    @classmethod
    def of(cls, session: WebSession) -> "SessionResult":
        return cls(
            signed_in_at=session.created_at.astimezone(EXCHANGE_TIMEZONE),
            expires_at=session.expires_at.astimezone(EXCHANGE_TIMEZONE),
            visit_started_at=_local(session.visit_started_at),
            previous_visit_at=_local(session.previous_visit_at),
        )


class SignOutAllResult(BaseModel):
    ended: int


# Settings (ADR 33 and ADR 37).


class BrokerSessionResult(BaseModel):
    broker: str
    connected: bool
    stored: bool = Field(description="A session is stored, live or expired.")
    expires_at: datetime | None
    connected_at: datetime | None = Field(description="The last login recorded.")
    configured: bool = Field(description="This machine has the broker's app keys.")
    redirect_url: str = Field(description="Register this as the broker app's redirect URL.")

    @classmethod
    def of(
        cls, session: BrokerSession, configured: bool, redirect_url: str
    ) -> "BrokerSessionResult":
        return cls(
            broker=session.broker,
            connected=session.connected,
            stored=session.stored,
            expires_at=_local(session.expires_at),
            connected_at=_local(session.connected_at),
            configured=configured,
            redirect_url=redirect_url,
        )


class InstrumentStatusResult(BaseModel):
    synced_at: datetime | None
    counts: dict[str, int] = Field(description="Contracts per exchange.")

    @classmethod
    def of(cls, status: InstrumentStatus) -> "InstrumentStatusResult":
        return cls(synced_at=_local(status.synced_at), counts=status.counts)


class ApiKeyResult(BaseModel):
    name: str
    prefix: str = Field(description="The key's first characters, to tell keys apart.")
    scope: str
    managed: bool = Field(description="Made by OpenTicker for a script run or an agent job.")
    created_at: datetime
    revoked_at: datetime | None

    @classmethod
    def of(cls, stored: StoredApiKey) -> "ApiKeyResult":
        return cls(
            name=stored.name,
            prefix=stored.prefix,
            scope=stored.scope,
            managed=stored.scope != FULL_SCOPE,
            created_at=stored.created_at.astimezone(EXCHANGE_TIMEZONE),
            revoked_at=_local(stored.revoked_at),
        )


class ApiKeysResult(BaseModel):
    keys: list[ApiKeyResult]


class CreatedKeyResult(BaseModel):
    key: ApiKeyResult
    secret: str = Field(description="The key itself. Shown this once; only its hash is kept.")


class LeverageResult(BaseModel):
    equity_intraday: float
    equity_delivery: float
    futures: float
    option_buy: float
    option_sell: float


class ChargeCheckSummary(BaseModel):
    checked_at: datetime
    differing: int
    checked: int
    skipped: int


class AccountResult(BaseModel):
    starting_capital: float
    capital_cap: float | None = Field(description="The most one position may be worth.")
    leverage: LeverageResult
    charges_source: str
    charges_as_of: date
    last_charge_check: ChargeCheckSummary | None

    @classmethod
    def of(
        cls, settings: SandboxSettings, cap: float | None, rates: ChargeRates
    ) -> "AccountResult":
        leverage = settings.leverage
        check = rates.last_check
        return cls(
            starting_capital=settings.starting_capital,
            capital_cap=cap,
            leverage=LeverageResult(
                equity_intraday=leverage.equity_intraday,
                equity_delivery=leverage.equity_delivery,
                futures=leverage.futures,
                option_buy=leverage.option_buy,
                option_sell=leverage.option_sell,
            ),
            charges_source=rates.source,
            charges_as_of=rates.as_of,
            last_charge_check=(
                ChargeCheckSummary(
                    checked_at=check.checked_at.astimezone(EXCHANGE_TIMEZONE),
                    differing=check.differing,
                    checked=check.checked,
                    skipped=check.skipped,
                )
                if check
                else None
            ),
        )


class ResetResult(BaseModel):
    capital: float
    orders: int = Field(description="Orders deleted.")
    trades: int = Field(description="Trades deleted.")
    positions: int = Field(description="Open positions deleted.")


class NotificationsResult(BaseModel):
    slack: bool
    email: bool


# The Dashboard (ADR 34).


class PointResult(BaseModel):
    minute: str = Field(description="HH:MM, exchange-local.")
    net_pnl: float


class SinceResult(BaseModel):
    at: datetime
    fills: int
    events: list[AuditEntryResult] = Field(
        description="Stops, kills, an expired session, refusals."
    )
    more_events: int
    pnl_change: float | None


class TodayResult(BaseModel):
    trading_date: date
    market_open: bool
    net_pnl: float | None = Field(
        description="After charges; None when an open position has no price."
    )
    before_charges: float | None
    charges: float
    fills: int
    realized_pnl: float
    unrealized_pnl: float | None
    complete: bool
    points: list[PointResult]
    since: SinceResult | None = Field(description="None on the day's first visit.")

    @classmethod
    def of(cls, today: Today) -> "TodayResult":
        figures = today.figures
        since = today.since
        return cls(
            trading_date=today.trading_date,
            market_open=today.market_open,
            net_pnl=figures.net_pnl,
            before_charges=figures.before_charges,
            charges=figures.charges,
            fills=figures.fills,
            realized_pnl=figures.realized_pnl,
            unrealized_pnl=figures.unrealized_pnl,
            complete=figures.complete,
            points=[
                PointResult(minute=p.minute.strftime("%H:%M"), net_pnl=p.net_pnl)
                for p in today.points
            ],
            since=(
                SinceResult(
                    at=since.at.astimezone(EXCHANGE_TIMEZONE),
                    fills=since.fills,
                    events=[AuditEntryResult.of(e) for e in since.events],
                    more_events=since.more_events,
                    pnl_change=since.pnl_change,
                )
                if since
                else None
            ),
        )


class SetupResult(BaseModel):
    broker: str
    broker_connected: bool
    instruments_synced_today: bool
    instrument_count: int
    agent_seen: str | None = Field(description="The first MCP client seen, by name.")
    first_fill_at: datetime | None
    done: bool

    @classmethod
    def of(cls, broker: str, state: SetupState) -> "SetupResult":
        return cls(
            broker=broker,
            broker_connected=state.broker_connected,
            instruments_synced_today=state.instruments_synced_today,
            instrument_count=state.instrument_count,
            agent_seen=state.agent_seen,
            first_fill_at=_local(state.first_fill_at),
            done=state.done,
        )


class AgentClientResult(BaseModel):
    name: str = Field(description="As the client gave it: claude-code, codex, ...")
    transport: str = Field(description="stdio or http.")
    version: str | None
    first_seen_at: datetime
    last_seen_at: datetime = Field(description="Written at most once a minute per client.")
    calls: int
    calls_today: int
    last_tool: str | None

    @classmethod
    def of(cls, client: AgentClient) -> "AgentClientResult":
        return cls(
            name=client.name,
            transport=client.transport,
            version=client.version,
            first_seen_at=client.first_seen_at.astimezone(EXCHANGE_TIMEZONE),
            last_seen_at=client.last_seen_at.astimezone(EXCHANGE_TIMEZONE),
            calls=client.calls,
            calls_today=client.calls_today,
            last_tool=client.last_tool,
        )


class AgentsResult(BaseModel):
    clients: list[AgentClientResult] = Field(description="Most recently seen first.")
    harness: Harness = Field(description="What review jobs run: claude or codex.")
    timeout_minutes: int
    jobs_per_day: int
    started_today: int

    @classmethod
    def of(
        cls, clients: list[AgentClient], settings: AgentSettings, started_today: int
    ) -> "AgentsResult":
        return cls(
            clients=[AgentClientResult.of(c) for c in clients],
            harness=settings.harness,
            timeout_minutes=int(settings.timeout.total_seconds() // 60),
            jobs_per_day=settings.jobs_per_day,
            started_today=started_today,
        )


# The browser's messages.


class Subscribe(BaseModel):
    type: Literal["subscribe"]
    instruments: list[InstrumentRef]


class Unsubscribe(BaseModel):
    type: Literal["unsubscribe"]
    instruments: list[InstrumentRef]


class Ping(BaseModel):
    type: Literal["ping"]


class ClientMessage(BaseModel):
    message: Annotated[Subscribe | Unsubscribe | Ping, Field(discriminator="type")]


# The server's messages.


class FeedStatusResult(BaseModel):
    broker: str
    broker_connected: bool
    broker_expires_at: datetime | None
    last_tick_at: datetime | None
    market_open: bool
    state: FeedState

    @classmethod
    def of(cls, status: FeedStatus) -> "FeedStatusResult":
        return cls(
            broker=status.broker,
            broker_connected=status.broker_connected,
            broker_expires_at=_local(status.broker_expires_at),
            last_tick_at=_local(status.last_tick_at),
            market_open=status.market_open,
            state=status.state,
        )


class HelloMessage(BaseModel):
    type: Literal["hello"] = "hello"
    server_time: datetime
    last_event_id: int  # 0 when the audit log is empty


class EventMessage(BaseModel):
    """A new audit log entry, whichever process wrote it (ADR 32)."""

    type: Literal["event"] = "event"
    entry: AuditEntryResult


class StatusMessage(BaseModel):
    type: Literal["status"] = "status"
    feed: FeedStatusResult


class TickMessage(BaseModel):
    type: Literal["tick"] = "tick"
    exchange: Exchange
    symbol: str
    last_price: float
    change: float | None  # since the previous session's close; None without one
    change_pct: float | None
    as_of: datetime
    streamed: bool  # from the live feed, not a quote

    @classmethod
    def of(cls, tick: Tick, close: float | None, streamed: bool) -> "TickMessage":
        change = round(tick.last_price - close, 2) if close else None
        return cls(
            exchange=tick.instrument.exchange,
            symbol=tick.instrument.symbol,
            last_price=tick.last_price,
            change=change,
            change_pct=round(change / close * 100, 2) if change is not None and close else None,
            as_of=tick.received_at.astimezone(EXCHANGE_TIMEZONE),
            streamed=streamed,
        )


class PongMessage(BaseModel):
    type: Literal["pong"] = "pong"


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    detail: str
