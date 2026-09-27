"""Results of the web app's own routes, and the stream's messages (ADR 31 and
ADR 32 in docs/adr). Times go out exchange-local, like every other result."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from openticker.adapters.inbound.mcp_models import InstrumentRef
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange, Tick
from openticker.storage.sqlite.web_repo import WebSession
from openticker.use_cases.feed_status import FeedState, FeedStatus

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
