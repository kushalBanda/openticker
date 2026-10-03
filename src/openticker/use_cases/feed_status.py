"""Where the web app's prices come from right now (ADR 32 in docs/adr): the
broker's live feed, quiet, the market closed, or no broker session at all."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from openticker.core.calendar.calendar import market_status
from openticker.ports.models import Exchange
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite.credentials_repo import get_credentials

QUIET_AFTER = timedelta(seconds=10)

FeedState = Literal["live", "quiet", "closed", "no-broker"]


@dataclass(frozen=True)
class FeedStatus:
    broker: str
    broker_connected: bool
    broker_expires_at: datetime | None
    last_tick_at: datetime | None
    market_open: bool
    state: FeedState


def feed_status(broker: str, last_tick_at: datetime | None, now: datetime) -> FeedStatus:
    """`last_tick_at`: when the live feed last priced anything."""
    credentials = get_credentials(broker)
    expires_at = credentials.expires_at if credentials else None
    connected = credentials is not None and (expires_at is None or expires_at > now)
    market_open = market_status(now, Exchange.NSE, load_calendar()).is_open
    state: FeedState
    if not connected:
        state = "no-broker"
    elif last_tick_at is not None and now - last_tick_at < QUIET_AFTER:
        state = "live"
    elif market_open:
        state = "quiet"
    else:
        state = "closed"
    return FeedStatus(broker, connected, expires_at, last_tick_at, market_open, state)
