"""Today's fills, newest first. Today is the exchange-local trading date."""

from datetime import datetime, time

from openticker.core.orders.models import Trade
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import EXCHANGE_TIMEZONE


def get_tradebook(broker: BrokerPort, limit: int, now: datetime) -> list[Trade]:
    return broker.get_trades(session_start(now), limit)


def session_start(now: datetime) -> datetime:
    """Midnight exchange-local of `now`'s date: no session runs past it."""
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    return datetime.combine(today, time(), tzinfo=EXCHANGE_TIMEZONE)
