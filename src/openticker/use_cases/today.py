"""The web app's Today (ADR 34 in docs/adr): the day's P&L after charges,
its minute line, and what happened since the browser's previous visit."""

from dataclasses import dataclass
from datetime import date, datetime

from openticker.core.calendar.calendar import market_status
from openticker.core.calendar.models import MarketCalendar
from openticker.core.pnl import DayFigures, IntradayPoint
from openticker.events.types import BrokerSessionExpired, OrderFailed, StrategyStopped
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange
from openticker.storage.sqlite import pnl_repo
from openticker.storage.sqlite.audit_repo import AuditEntry, list_audit
from openticker.use_cases.pnl_history import figures_on, trading_day

# What "since you were here" names, besides counting fills.
NAMED = (StrategyStopped.__name__, BrokerSessionExpired.__name__, OrderFailed.__name__)
MOST_NAMED = 3


@dataclass(frozen=True)
class SinceLastVisit:
    at: datetime
    fills: int
    events: tuple[AuditEntry, ...]  # stops, kills, an expired session, refusals: newest first
    more_events: int  # happened too, not named
    pnl_change: float | None  # None when no point was recorded by then


@dataclass(frozen=True)
class Today:
    trading_date: date
    market_open: bool
    figures: DayFigures
    points: tuple[IntradayPoint, ...]
    since: SinceLastVisit | None  # None on the day's first visit


def today(
    broker: BrokerPort,
    previous_visit_at: datetime | None,
    calendar: MarketCalendar,
    now: datetime,
) -> Today:
    day = trading_day(now, calendar)
    figures = figures_on(day, broker.get_positions())
    points = tuple(pnl_repo.points_on(day))
    since = None
    if (
        previous_visit_at is not None
        and previous_visit_at.astimezone(EXCHANGE_TIMEZONE).date() == day
    ):
        since = _since(previous_visit_at, figures, points, now)
    return Today(
        trading_date=day,
        market_open=market_status(now, Exchange.NSE, calendar).is_open,
        figures=figures,
        points=points,
        since=since,
    )


def _since(
    at: datetime, figures: DayFigures, points: tuple[IntradayPoint, ...], now: datetime
) -> SinceLastVisit:
    events = list_audit(50, event_types=NAMED, since=at)
    minute = at.astimezone(EXCHANGE_TIMEZONE).time()
    then = [p for p in points if p.minute <= minute]
    change = (
        round(figures.net_pnl - then[-1].net_pnl, 2)
        if then and figures.net_pnl is not None
        else None
    )
    return SinceLastVisit(
        at=at,
        fills=len(pnl_repo.fills_between(at, now)),
        events=tuple(events[:MOST_NAMED]),
        more_events=max(0, len(events) - MOST_NAMED),
        pnl_change=change,
    )
