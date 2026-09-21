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
    expires_at: Mapped[str | None]  # ISO 8601, tz-aware — stored as text, parsed at the repo boundary


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
