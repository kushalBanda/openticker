from datetime import UTC, datetime, timedelta

import pytest

from openticker.core.strategies.prices import (
    PriceTimeouts,
    is_stale,
    needs_polling,
    watched_since,
)

OPEN = datetime(2026, 9, 22, 3, 45, tzinfo=UTC)  # 09:15 IST
ENTERED = OPEN + timedelta(minutes=5)
T = PriceTimeouts()


def test_age_counts_from_the_entry_or_the_session_open() -> None:
    assert watched_since(ENTERED, OPEN) == ENTERED
    assert watched_since(ENTERED - timedelta(days=1), OPEN) == OPEN  # held overnight
    assert watched_since(None, OPEN) == OPEN


def test_no_streamed_price_for_ten_seconds_needs_polling() -> None:
    assert not needs_polling(ENTERED, None, ENTERED + timedelta(seconds=9), T)
    assert needs_polling(ENTERED, None, ENTERED + timedelta(seconds=10), T)
    tick = ENTERED + timedelta(seconds=5)
    assert not needs_polling(ENTERED, tick, tick + timedelta(seconds=9), T)
    assert needs_polling(ENTERED, tick, tick + timedelta(seconds=10), T)


def test_a_streamed_price_from_before_the_entry_does_not_count() -> None:
    old = ENTERED - timedelta(minutes=1)

    assert not needs_polling(ENTERED, old, ENTERED + timedelta(seconds=5), T)
    assert needs_polling(ENTERED, old, ENTERED + timedelta(seconds=10), T)


def test_no_price_from_either_source_for_a_minute_is_stale() -> None:
    assert not is_stale(ENTERED, None, ENTERED + timedelta(seconds=59), T)
    assert is_stale(ENTERED, None, ENTERED + timedelta(seconds=60), T)


def test_an_illiquid_leg_priced_by_quotes_is_never_stale() -> None:
    later = ENTERED + timedelta(minutes=30)
    quoted = later - timedelta(seconds=2)  # no trade for half an hour, but quotes answer

    assert not is_stale(ENTERED, quoted, later, T)


def test_polling_must_come_before_stale() -> None:
    with pytest.raises(ValueError, match="must come before stale"):
        PriceTimeouts(poll_after=timedelta(seconds=60), stale_after=timedelta(seconds=60))
    with pytest.raises(ValueError):
        PriceTimeouts(poll_after=timedelta(0))


def test_a_restarted_daemon_gives_every_leg_its_full_window() -> None:
    restarted = ENTERED + timedelta(minutes=90)

    assert watched_since(ENTERED, OPEN, restarted) == restarted
    assert watched_since(ENTERED, OPEN, OPEN - timedelta(days=1)) == ENTERED
