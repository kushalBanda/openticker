"""What the web app's Settings page shows (ADR 33 and ADR 37 in docs/adr): the
broker session, the instrument list, the paper account and its charges.
Never a secret: no session token, no key, no notification setting."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from openticker.core.orders.charges import ChargeBook
from openticker.events.types import BrokerConnected, ChargeRatesChecked, InstrumentSyncCompleted
from openticker.storage.sqlite.audit_repo import AuditEntry, list_audit
from openticker.storage.sqlite.credentials_repo import get_credentials
from openticker.storage.sqlite.instruments_repo import count_by_exchange


@dataclass(frozen=True)
class BrokerSession:
    broker: str
    connected: bool  # stored and not past its expiry
    stored: bool  # a session is stored, live or expired
    expires_at: datetime | None
    connected_at: datetime | None  # the last login recorded; None before any


@dataclass(frozen=True)
class InstrumentStatus:
    synced_at: datetime | None  # the last sync recorded; None before any
    counts: dict[str, int]  # contracts per exchange


@dataclass(frozen=True)
class ChargeCheck:
    checked_at: datetime
    differing: int
    checked: int
    skipped: int


@dataclass(frozen=True)
class ChargeRates:
    source: str
    as_of: date  # the oldest schedule's date
    last_check: ChargeCheck | None


def broker_session(broker: str, now: datetime) -> BrokerSession:
    credentials = get_credentials(broker)
    expires_at = credentials.expires_at if credentials else None
    login = _latest(BrokerConnected.__name__, lambda payload: payload.get("broker") == broker)
    return BrokerSession(
        broker=broker,
        connected=credentials is not None and (expires_at is None or expires_at > now),
        stored=credentials is not None,
        expires_at=expires_at,
        connected_at=login.occurred_at if login else None,
    )


def instrument_status() -> InstrumentStatus:
    synced = _latest(InstrumentSyncCompleted.__name__)
    return InstrumentStatus(synced.occurred_at if synced else None, count_by_exchange())


def charge_rates(book: ChargeBook) -> ChargeRates:
    schedules = list(book.schedules.values())
    checked = _latest(ChargeRatesChecked.__name__)
    last_check = None
    if checked is not None:
        payload = json.loads(checked.payload)
        last_check = ChargeCheck(
            checked.occurred_at, payload["differing"], payload["checked"], payload["skipped"]
        )
    return ChargeRates(
        source=schedules[0].source if schedules else "",
        as_of=min(schedule.as_of for schedule in schedules) if schedules else date.min,
        last_check=last_check,
    )


_LOOK_BACK = 50  # entries of one kind searched for a match


def _latest(
    event_type: str, matches: Callable[[dict[str, Any]], bool] | None = None
) -> AuditEntry | None:
    for entry in list_audit(_LOOK_BACK if matches else 1, event_type):
        if matches is None or matches(json.loads(entry.payload)):
            return entry
    return None
