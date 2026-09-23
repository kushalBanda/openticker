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
    triggered_by: Mapped[str | None]
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
    """One row. Available cash is derived: capital - used margin + realized P&L."""

    __tablename__ = "sandbox_funds"

    id: Mapped[int] = mapped_column(primary_key=True)
    total_capital: Mapped[float]
    used_margin: Mapped[float]
    realized_pnl: Mapped[float]


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
    kind: Mapped[str]  # "options"; "signal" comes with alert strategies
    definition: Mapped[str]
    mode: Mapped[str]  # "sandbox"; live trading has no design yet (ADR 6)
    locked: Mapped[bool]  # the kill switch
    created_at: Mapped[datetime]  # UTC, stored naive
    updated_at: Mapped[datetime]  # UTC, stored naive
    deleted_at: Mapped[datetime | None]  # UTC, stored naive
    # The broker scheduled entries go through; NULL: not scheduled (ADR 22 in
    # docs/adr). Nullable, so it can be added to an existing table (ADR 18).
    scheduled_broker: Mapped[str | None]


# Strategy runs (ADR 21 in docs/adr). The MCP server and the REST API write
# commands; the daemon's runner carries them out and owns the rest.


class StrategyCommandRow(Base):
    __tablename__ = "strategy_commands"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str]  # start, stop, kill, close_leg
    leg_id: Mapped[str | None]  # close_leg only
    broker: Mapped[str | None]  # start only
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
