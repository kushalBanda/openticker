"""Fills since the start of today, this week or this month, newest first.
Days are exchange-local trading dates."""

from datetime import datetime, time, timedelta
from typing import Literal

from openticker.core.orders.models import Trade
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import EXCHANGE_TIMEZONE

Period = Literal["today", "week", "month"]


def get_tradebook(
    broker: BrokerPort, limit: int, now: datetime, period: Period = "today"
) -> list[Trade]:
    return broker.get_trades(period_start(now, period), limit)


def period_start(now: datetime, period: Period) -> datetime:
    """Midnight exchange-local of today, this Monday, or the 1st of the month."""
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    if period == "week":
        today -= timedelta(days=today.weekday())
    elif period == "month":
        today = today.replace(day=1)
    return datetime.combine(today, time(), tzinfo=EXCHANGE_TIMEZONE)


def session_start(now: datetime) -> datetime:
    """Midnight exchange-local of `now`'s date: no session runs past it."""
    return period_start(now, "today")
