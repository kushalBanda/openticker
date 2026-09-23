"""When a strategy leg's price is live, needs polling, or is stale. Pure.
Rules: ADR 13 and ADR 23 in docs/adr."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class PriceTimeouts:
    poll_after: timedelta = timedelta(seconds=10)  # no streamed price: fetch quotes
    stale_after: timedelta = timedelta(seconds=60)  # no price from either: stop the run

    def __post_init__(self) -> None:
        if not timedelta(0) < self.poll_after < self.stale_after:
            raise ValueError(
                f"the polling fallback ({self.poll_after}) must come before stale "
                f"({self.stale_after}), and both after zero"
            )


def watched_since(
    entered_at: datetime | None,
    session_opens_at: datetime,
    watching_from: datetime | None = None,
) -> datetime:
    """Where a leg's price age is counted from: the latest of its entry,
    today's open (for a leg held overnight) and when the daemon started
    watching (after a restart, it has no price in memory). No price is
    expected before any of them."""
    return max(moment for moment in (entered_at, session_opens_at, watching_from) if moment)


def needs_polling(
    since: datetime, last_streamed_at: datetime | None, now: datetime, timeouts: PriceTimeouts
) -> bool:
    latest = since if last_streamed_at is None else max(last_streamed_at, since)
    return now - latest >= timeouts.poll_after


def is_stale(
    since: datetime, last_price_at: datetime | None, now: datetime, timeouts: PriceTimeouts
) -> bool:
    """No price from the stream or from quotes for `stale_after`. A quote
    counts even for a contract that hasn't traded: it still names a price."""
    latest = since if last_price_at is None else max(last_price_at, since)
    return now - latest >= timeouts.stale_after
