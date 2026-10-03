"""The paper account's P&L by day and by minute (ADR 34 in docs/adr).

The daemon records a point each minute of the session and, after the close,
the day. Today is never read from the record while it runs: it is worked
out now, from the day's fills and the open positions marked by the broker.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from openticker.core.calendar.calendar import session_hours
from openticker.core.calendar.models import MarketCalendar
from openticker.core.pnl import DayFigures, DayPnl, IntradayPoint, day_figures, day_pnl
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange, Position
from openticker.storage.sqlite import pnl_repo

MAX_DAYS = 400
POINTS_KEPT = timedelta(days=30)


class HistoryRangeError(ValueError):
    pass


def trading_day(now: datetime, calendar: MarketCalendar) -> date:
    """Today when NSE trades today, else the last day it did."""
    day = now.astimezone(EXCHANGE_TIMEZONE).date()
    for _ in range(31):
        if session_hours(day, Exchange.NSE, calendar) is not None:
            return day
        day -= timedelta(days=1)
    return now.astimezone(EXCHANGE_TIMEZONE).date()


def day_window(trading_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(trading_date, time(), EXCHANGE_TIMEZONE)
    return start, start + timedelta(days=1)


def figures_on(trading_date: date, positions: list[Position]) -> DayFigures:
    """The day's figures with open positions as `positions` mark them."""
    start, end = day_window(trading_date)
    carried = pnl_repo.last_day_before(trading_date)
    return day_figures(
        pnl_repo.fills_between(start, end),
        [p.unrealized_pnl for p in positions if p.quantity],
        carried.open_value or 0.0 if carried else 0.0,
    )


def open_value(positions: list[Position]) -> float | None:
    values = [p.unrealized_pnl for p in positions if p.quantity]
    return None if any(v is None for v in values) else round(sum(v or 0.0 for v in values), 2)


def record_intraday_point(broker: BrokerPort, now: datetime) -> IntradayPoint | None:
    """This minute's point; None when an open position has no price (a gap
    in the line, never a guess)."""
    local = now.astimezone(EXCHANGE_TIMEZONE)
    figures = figures_on(local.date(), broker.get_positions())
    if figures.net_pnl is None or figures.unrealized_pnl is None:
        return None
    point = IntradayPoint(
        minute=local.time().replace(second=0, microsecond=0),
        net_pnl=figures.net_pnl,
        realized_pnl=figures.realized_pnl,
        charges=figures.charges,
        unrealized_pnl=figures.unrealized_pnl,
    )
    pnl_repo.upsert_point(local.date(), point)
    return point


def record_daily_pnl(trading_date: date, broker: BrokerPort, now: datetime) -> DayPnl:
    """The day, after its close. Open positions are marked by the broker;
    when it can't price them, by the day's last minute point, and the day is
    marked estimated. Prunes minute points older than 30 days."""
    try:
        positions = broker.get_positions()
    except BrokerError:
        positions = None
    figures = figures_on(trading_date, positions or [])
    value = open_value(positions) if positions is not None else None
    estimated = positions is None or value is None
    if estimated:
        points = pnl_repo.points_on(trading_date)
        last = points[-1] if points else None
        carried = pnl_repo.last_day_before(trading_date)
        base = carried.open_value or 0.0 if carried else 0.0
        unrealized = last.unrealized_pnl if last else None
        figures = DayFigures(
            realized_pnl=figures.realized_pnl,
            charges=figures.charges,
            fills=figures.fills,
            unrealized_pnl=unrealized,
            complete=figures.complete,
        )
        value = None if unrealized is None else round(unrealized + base, 2)
    day = day_pnl(trading_date, figures, value, estimated)
    pnl_repo.upsert_day(day, now)
    pnl_repo.prune_points(trading_date - POINTS_KEPT)
    return day


@dataclass(frozen=True)
class PnlHistory:
    days: list[DayPnl]  # oldest first
    live: date | None  # the day worked out now, not read from the record


def get_pnl_history(
    start: date, end: date, broker: BrokerPort, calendar: MarketCalendar, now: datetime
) -> PnlHistory:
    """Recorded days in the range, oldest first, and today worked out live
    while it isn't recorded yet."""
    if end < start:
        raise HistoryRangeError(f"to_date {end} is before from_date {start}")
    if (end - start).days + 1 > MAX_DAYS:
        raise HistoryRangeError(f"at most {MAX_DAYS} days at once; ask for a shorter range")
    days = pnl_repo.days_between(start, end)
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    trades_today = session_hours(today, Exchange.NSE, calendar) is not None
    if start <= today <= end and trades_today and not any(d.trading_date == today for d in days):
        positions = broker.get_positions()
        days.append(day_pnl(today, figures_on(today, positions), open_value(positions)))
        return PnlHistory(days, today)
    return PnlHistory(days, None)


@dataclass(frozen=True)
class ChargeTotals:
    month: str  # "2026-09"
    by_type: dict[str, float]  # brokerage, transaction_tax, exchange, sebi, stamp_duty, gst
    total: float
    fills: int
    unitemized: float  # charged before each charge was recorded


def get_charges_summary(start: date, end: date) -> list[ChargeTotals]:
    """Charges paid, month by month (exchange-local), oldest first."""
    if end < start:
        raise HistoryRangeError(f"to_date {end} is before from_date {start}")
    if (end - start).days + 1 > MAX_DAYS:
        raise HistoryRangeError(f"at most {MAX_DAYS} days at once; ask for a shorter range")
    months: dict[str, ChargeTotals] = {}
    for fill in pnl_repo.charges_between(day_window(start)[0], day_window(end)[1]):
        key = fill.filled_at.astimezone(EXCHANGE_TIMEZONE).strftime("%Y-%m")
        was = months.get(key) or ChargeTotals(key, {}, 0.0, 0, 0.0)
        by_type = dict(was.by_type)
        for name, amount in (fill.detail or {}).items():
            by_type[name] = round(by_type.get(name, 0.0) + amount, 2)
        charged = fill.charges or 0.0
        months[key] = ChargeTotals(
            month=key,
            by_type=by_type,
            total=round(was.total + charged, 2),
            fills=was.fills + 1,
            unitemized=round(was.unitemized + (0.0 if fill.detail else charged), 2),
        )
    return list(months.values())
