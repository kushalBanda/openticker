"""SQLAlchemy table definitions."""

from datetime import date, datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CredentialRow(Base):
    __tablename__ = "credentials"

    broker: Mapped[str] = mapped_column(primary_key=True)
    access_token_encrypted: Mapped[bytes]
    refresh_token_encrypted: Mapped[bytes | None]
    expires_at: Mapped[
        str | None
    ]  # ISO 8601, tz-aware — stored as text, parsed at the repo boundary


class InstrumentRow(Base):
    """Keyed by our standardized (exchange, symbol) — the pair every caller looks up by.
    No broker column yet: Zerodha is the only broker, so `token` is its token."""

    __tablename__ = "instruments"

    exchange: Mapped[str] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(primary_key=True)
    broker_symbol: Mapped[str]
    broker_exchange: Mapped[str]
    token: Mapped[str]
    expiry: Mapped[date | None]
    strike: Mapped[float | None]
    lot_size: Mapped[int]
    instrument_type: Mapped[str]
    tick_size: Mapped[float]


class AuditLogRow(Base):
    """Append-only record of every domain event. Never updated or deleted."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime]  # UTC, stored naive
    event_type: Mapped[str] = mapped_column(index=True)
    triggered_by: Mapped[str | None] = mapped_column(index=True)  # the Activity page's "who"
    payload: Mapped[str]  # the event's fields as JSON


# Sandbox (paper trading) tables, kept apart from anything live (ADR 11 in docs/adr).


class SandboxOrderRow(Base):
    __tablename__ = "sandbox_orders"

    order_id: Mapped[str] = mapped_column(primary_key=True)
    placed_at: Mapped[datetime] = mapped_column(index=True)  # UTC, stored naive
    exchange: Mapped[str]
    symbol: Mapped[str]
    side: Mapped[str]
    quantity: Mapped[int]
    product: Mapped[str]
    order_type: Mapped[str]
    status: Mapped[str]
    fill_price: Mapped[float | None]
    reason: Mapped[str | None]
    triggered_by: Mapped[str]
    strategy_id: Mapped[str | None] = mapped_column(index=True)
    run_id: Mapped[str | None] = mapped_column(index=True)
    # Resting orders. Nullable, so they can be added to an existing table (ADR 18 in docs/adr).
    price: Mapped[float | None]
    trigger_price: Mapped[float | None]
    triggered: Mapped[bool | None]  # SL: trigger crossed, now resting as a limit
    reserved_margin: Mapped[float | None]  # held in used_margin while pending
    updated_at: Mapped[datetime | None]  # UTC, stored naive: filled, cancelled or expired


class SandboxTradeRow(Base):
    __tablename__ = "sandbox_trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(index=True)
    filled_at: Mapped[datetime]  # UTC, stored naive
    exchange: Mapped[str]
    symbol: Mapped[str]
    side: Mapped[str]
    quantity: Mapped[int]
    price: Mapped[float]
    product: Mapped[str]
    strategy_id: Mapped[str | None] = mapped_column(index=True)
    run_id: Mapped[str | None] = mapped_column(index=True)
    # Costs (ADR 28 in docs/adr). Nullable, so they can be added to an existing
    # table (ADR 18); NULL: filled before costs were modelled.
    charges: Mapped[float | None]
    expected_price: Mapped[float | None]  # what the order was placed against
    # NULL: filled before they were recorded.
    realized_pnl: Mapped[float | None]  # what this fill closed, before charges
    charges_detail: Mapped[str | None]  # JSON: each charge, and "gst"; they sum to `charges`


class SandboxPositionRow(Base):
    """Net position per instrument and product. Rows stay once flat, keeping
    the realized P&L."""

    __tablename__ = "sandbox_positions"

    exchange: Mapped[str] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(primary_key=True)
    product: Mapped[str] = mapped_column(primary_key=True)
    quantity: Mapped[int]  # signed: negative is short
    average_price: Mapped[float]
    margin_blocked: Mapped[float]
    realized_pnl: Mapped[float]


class SandboxFundsRow(Base):
    """One row. Available cash is derived: capital - used margin + realized
    P&L - charges paid."""

    __tablename__ = "sandbox_funds"

    id: Mapped[int] = mapped_column(primary_key=True)
    total_capital: Mapped[float]
    used_margin: Mapped[float]
    realized_pnl: Mapped[float]
    charges: Mapped[float | None]  # added with costs (ADR 28); NULL is 0


class ApiKeyRow(Base):
    """REST API keys. Only a hash of each key is stored (ADR 17 in docs/adr)."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True)
    key_hash: Mapped[str] = mapped_column(unique=True)
    prefix: Mapped[str]  # the key's first characters, to tell keys apart in a listing
    scope: Mapped[str]  # "full"; narrower scopes come with script hosting
    created_at: Mapped[datetime]  # UTC, stored naive
    revoked_at: Mapped[datetime | None]  # UTC, stored naive


class StrategyRow(Base):
    """Strategy definitions (ADR 20 in docs/adr). `definition` is versioned
    JSON; a deleted strategy keeps its row, so orders it placed still name it."""

    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(index=True)  # unique among strategies not deleted
    kind: Mapped[str]  # "options" (ADR 20) or "signal" (ADR 24)
    definition: Mapped[str]
    mode: Mapped[str]  # "sandbox"; live trading has no design yet (ADR 6)
    locked: Mapped[bool]  # the kill switch
    created_at: Mapped[datetime]  # UTC, stored naive
    updated_at: Mapped[datetime]  # UTC, stored naive
    deleted_at: Mapped[datetime | None]  # UTC, stored naive
    # The broker scheduled entries go through; NULL: not scheduled (ADR 22 in
    # docs/adr). Nullable, so it can be added to an existing table (ADR 18).
    scheduled_broker: Mapped[str | None]
    # When it is reviewed without being asked, as JSON; NULL: only on
    # start_review (ADR 29 in docs/adr).
    review_schedule: Mapped[str | None]


# Strategy runs (ADR 21 in docs/adr). The MCP server and the REST API write
# commands; the daemon's runner carries them out and owns the rest.


class StrategyCommandRow(Base):
    __tablename__ = "strategy_commands"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str]  # start, stop, kill, close_leg, signal
    leg_id: Mapped[str | None]  # close_leg and signal only
    broker: Mapped[str | None]  # start and signal only
    # signal only: long_entry, long_exit, short_entry, short_exit (ADR 24 in
    # docs/adr). Nullable, so it can be added to an existing table (ADR 18).
    action: Mapped[str | None]
    triggered_by: Mapped[str]
    status: Mapped[str] = mapped_column(index=True)  # pending, done, refused
    outcome: Mapped[str | None]
    created_at: Mapped[datetime]  # UTC, stored naive
    processed_at: Mapped[datetime | None]  # UTC, stored naive


class StrategyRunRow(Base):
    __tablename__ = "strategy_runs"

    id: Mapped[str] = mapped_column(primary_key=True)
    strategy_id: Mapped[str] = mapped_column(index=True)
    broker: Mapped[str]
    product: Mapped[str]
    status: Mapped[str] = mapped_column(index=True)  # open, stopping, ended
    trigger: Mapped[str]
    started_at: Mapped[datetime]  # UTC, stored naive
    ended_at: Mapped[datetime | None]  # UTC, stored naive
    stop_reason: Mapped[str | None]
    stop_detail: Mapped[str | None]
    legs: Mapped[str]  # JSON: each leg's contract, state and ratchets
    peak_mtm: Mapped[float]
    trough_mtm: Mapped[float | None]  # nullable: added after the table (ADR 18); NULL is 0
    lock_floor: Mapped[float | None]
    stops_at_entry: Mapped[bool]
    realized_pnl: Mapped[float]


class StrategyOrderRow(Base):
    """Written before the order is sent, so a crash in between leaves a
    record of what was about to happen."""

    __tablename__ = "strategy_orders"

    id: Mapped[str] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(index=True)
    leg_id: Mapped[str]
    intent: Mapped[str]  # entry, exit
    symbol: Mapped[str]
    exchange: Mapped[str]
    side: Mapped[str]
    quantity: Mapped[int]
    status: Mapped[str]  # pending until the sandbox answers, then its order status
    sandbox_order_id: Mapped[str | None]
    fill_price: Mapped[float | None]
    reason: Mapped[str | None]
    created_at: Mapped[datetime]  # UTC, stored naive
    updated_at: Mapped[datetime | None]  # UTC, stored naive


class StrategyEventRow(Base):
    """A run's timeline, in the words a user reads."""

    __tablename__ = "strategy_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(index=True)
    occurred_at: Mapped[datetime]  # UTC, stored naive
    message: Mapped[str]


# Signal strategies' alert URLs and every call made to them (ADR 24 in docs/adr).


class StrategyWebhookRow(Base):
    """One alert URL per signal strategy. Only the token's SHA-256 is kept:
    the URL is shown once, when it is made."""

    __tablename__ = "strategy_webhooks"

    strategy_id: Mapped[str] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(unique=True)
    broker: Mapped[str]  # the broker its signals' orders are priced through
    allowed_ips: Mapped[str]  # JSON list of addresses and CIDR ranges; empty allows any
    created_at: Mapped[datetime]  # UTC, stored naive


class StrategySignalRow(Base):
    """Every call to a known alert URL, and what became of it."""

    __tablename__ = "strategy_signals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(index=True)
    received_at: Mapped[datetime] = mapped_column(index=True)  # UTC, stored naive
    client_ip: Mapped[str | None]
    result: Mapped[str]  # accepted, ignored, refused, locked, forbidden, rate_limited
    message: Mapped[str]
    alert_format: Mapped[str | None]  # chartink or json, once the body was read
    payload: Mapped[str | None]  # the body, with the token and secrets removed, capped
    command_ids: Mapped[str | None]  # JSON list: the signal commands it wrote


# Hosted Python scripts (ADR 25 in docs/adr). The MCP server and the REST API
# write commands; the daemon's supervisor starts and stops the processes and
# owns the runs. The source and each run's output are files under
# $OPENTICKER_HOME/scripts/<id>/.


class ScriptRow(Base):
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    source_sha256: Mapped[str]
    source_bytes: Mapped[int]
    schedule: Mapped[str | None]  # JSON; NULL: runs only on start_script
    created_at: Mapped[datetime]  # UTC, stored naive
    updated_at: Mapped[datetime]  # UTC, stored naive


class ScriptCommandRow(Base):
    __tablename__ = "script_commands"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    script_id: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str]  # start, stop
    triggered_by: Mapped[str]
    status: Mapped[str] = mapped_column(index=True)  # pending, done, refused
    outcome: Mapped[str | None]
    created_at: Mapped[datetime]  # UTC, stored naive
    processed_at: Mapped[datetime | None]  # UTC, stored naive


class ScriptRunRow(Base):
    __tablename__ = "script_runs"

    id: Mapped[str] = mapped_column(primary_key=True)
    script_id: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(index=True)  # running, stopping, ended
    trigger: Mapped[str]
    started_at: Mapped[datetime]  # UTC, stored naive
    pid: Mapped[int | None]  # NULL until the process exists
    stop_reason: Mapped[str | None]  # while stopping, the reason it was asked to
    stop_detail: Mapped[str | None]
    stop_requested_at: Mapped[datetime | None]  # UTC, stored naive
    exit_code: Mapped[int | None]
    ended_at: Mapped[datetime | None]  # UTC, stored naive
    peak_memory_kb: Mapped[int | None]  # highest measured; NULL: never measured


class AgentJobRow(Base):
    """One headless run of the user's coding agent (ADR 29 in docs/adr)."""

    __tablename__ = "agent_jobs"

    id: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str]  # review
    strategy_id: Mapped[str] = mapped_column(index=True)
    harness: Mapped[str]  # claude, codex
    status: Mapped[str] = mapped_column(index=True)  # pending, running, stopping, ended
    trigger: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(index=True)  # UTC, stored naive
    started_at: Mapped[datetime | None]  # UTC, stored naive
    pid: Mapped[int | None]
    stop_requested_at: Mapped[datetime | None]  # UTC, stored naive
    end_reason: Mapped[str | None]
    end_detail: Mapped[str | None]
    exit_code: Mapped[int | None]
    ended_at: Mapped[datetime | None]  # UTC, stored naive
    summary: Mapped[str | None]  # the agent's final answer, capped
    cost_usd: Mapped[float | None]


# The web app's browser sign-in (ADR 31 in docs/adr). Only hashes of the
# link tokens and session secrets are stored.


class SignInLinkRow(Base):
    __tablename__ = "ui_sign_in_links"

    token_hash: Mapped[str] = mapped_column(primary_key=True)
    created_at: Mapped[datetime]  # UTC, stored naive
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class WebSessionRow(Base):
    __tablename__ = "ui_sessions"

    id_hash: Mapped[str] = mapped_column(primary_key=True)
    created_at: Mapped[datetime]  # UTC, stored naive
    expires_at: Mapped[datetime]  # sliding: pushed on while the session is used
    last_seen_at: Mapped[datetime]
    visit_started_at: Mapped[datetime | None]
    previous_visit_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    user_agent: Mapped[str | None]


# MCP clients that have called a tool (ADR 35 in docs/adr): Claude Code,
# Codex, ... by the name each gives in its initialize handshake.


class AgentClientRow(Base):
    __tablename__ = "agent_clients"

    name: Mapped[str] = mapped_column(primary_key=True)
    transport: Mapped[str] = mapped_column(primary_key=True)  # stdio, http
    version: Mapped[str | None]
    first_seen_at: Mapped[datetime]  # UTC, stored naive
    last_seen_at: Mapped[datetime]
    calls: Mapped[int]
    last_tool: Mapped[str | None]  # NULL on rows from before it was kept
    day: Mapped[date | None]  # exchange-local day `calls_today` counts
    calls_today: Mapped[int | None]


# The paper account's P&L by day and by minute (ADR 34 in docs/adr).


class DailyPnlRow(Base):
    """One row per trading day, written after its close."""

    __tablename__ = "daily_pnl"

    trading_date: Mapped[date] = mapped_column(primary_key=True)
    realized_pnl: Mapped[float]
    charges: Mapped[float]
    unrealized_pnl: Mapped[float | None]  # NULL: an open position had no price
    net_pnl: Mapped[float | None]
    open_value: Mapped[float | None]  # open positions' unrealized P&L at the close
    fills: Mapped[int]
    complete: Mapped[bool]  # every fill recorded what it realized
    estimated: Mapped[bool]  # closing marks were the last prices known
    recorded_at: Mapped[datetime]  # UTC, stored naive


class IntradayPnlRow(Base):
    """A point a minute through the session; kept 30 days."""

    __tablename__ = "intraday_pnl"

    trading_date: Mapped[date] = mapped_column(primary_key=True)
    minute: Mapped[str] = mapped_column(primary_key=True)  # "HH:MM", exchange-local
    net_pnl: Mapped[float]
    realized_pnl: Mapped[float]
    charges: Mapped[float]
    unrealized_pnl: Mapped[float]


# Named lists of instruments to watch (ADR 36 in docs/adr), shared by the web
# app and agents.


class WatchlistRow(Base):
    __tablename__ = "watchlists"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    position: Mapped[int]  # lists in the order they were made
    created_at: Mapped[datetime]  # UTC, stored naive


class WatchlistItemRow(Base):
    __tablename__ = "watchlist_items"

    watchlist_id: Mapped[str] = mapped_column(primary_key=True)
    exchange: Mapped[str] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int]  # instruments in the order they were added
