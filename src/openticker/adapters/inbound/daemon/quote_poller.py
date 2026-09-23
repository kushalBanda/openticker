"""Fetches quotes for strategy legs the live feed has gone quiet on (ADR 13
and ADR 23 in docs/adr): every couple of seconds, one batch per broker, for
each leg with no streamed price for the polling fallback. The feed stays
subscribed, so the next streamed price takes over again. A rate-limited
broker is left alone for a while, and its legs keep ageing towards stale."""

import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.core.strategies.prices import PriceTimeouts, needs_polling
from openticker.ports.errors import BrokerRateLimitError
from openticker.ports.models import Instrument, Quote, Tick
from openticker.use_cases.strategies.runner import WatchedLeg

log = logging.getLogger(__name__)

POLL_EVERY = timedelta(seconds=2)
# After a rate limit: the pause before the next attempt, longer each time in a row.
RATE_LIMIT_BACKOFF = (
    timedelta(seconds=2),
    timedelta(seconds=5),
    timedelta(seconds=10),
    timedelta(seconds=30),
)


class QuotePoller:
    def __init__(
        self,
        quotes: Callable[[str, list[Instrument]], list[Quote]],  # by broker name
        prices: LatestPrices,
        timeouts: PriceTimeouts,
    ) -> None:
        self._quotes = quotes
        self._prices = prices
        self._timeouts = timeouts
        self._paused_until: dict[str, datetime] = {}
        self._rate_limits: dict[str, int] = defaultdict(int)
        self._last_poll: datetime | None = None

    def poll(self, watched: list[WatchedLeg], now: datetime) -> None:
        if self._last_poll is not None and now - self._last_poll < POLL_EVERY:
            return
        self._last_poll = now
        due: dict[str, dict[tuple[str, str], Instrument]] = defaultdict(dict)
        for leg in watched:
            streamed = self._prices.streamed_at(leg.instrument)
            if needs_polling(leg.since, streamed, now, self._timeouts):
                key = (leg.instrument.exchange, leg.instrument.symbol)
                due[leg.broker][key] = leg.instrument
        for broker, instruments in due.items():
            paused = self._paused_until.get(broker)
            if paused is not None and now < paused:
                continue
            try:
                quotes = self._quotes(broker, list(instruments.values()))
            except BrokerRateLimitError:
                pause = RATE_LIMIT_BACKOFF[
                    min(self._rate_limits[broker], len(RATE_LIMIT_BACKOFF) - 1)
                ]
                self._rate_limits[broker] += 1
                self._paused_until[broker] = now + pause
                log.warning("%s quotes rate limited; polling again in %ss", broker, pause.seconds)
                continue
            except Exception as exc:  # noqa: BLE001 — a failed poll must never stop the runs being judged
                log.warning(
                    "%s quotes for strategy legs failed: %s: %s", broker, type(exc).__name__, exc
                )
                continue
            self._rate_limits[broker] = 0
            self._prices.update_polled(Tick(q.instrument, q.last_price, now) for q in quotes)
