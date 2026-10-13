from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.core.calendar.models import SessionHours
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange, Tick
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.strategies import NOW


def test_a_polled_quote_prices_an_instrument_without_counting_as_streamed() -> None:
    prices = LatestPrices()

    prices.update_polled([Tick(FAKE_INSTRUMENT, 100.0, NOW)])

    assert prices.get(FAKE_INSTRUMENT) == Tick(FAKE_INSTRUMENT, 100.0, NOW)
    assert prices.streamed_at(FAKE_INSTRUMENT) is None


def test_a_polled_quote_never_replaces_a_newer_streamed_price() -> None:
    prices = LatestPrices()
    prices.update([Tick(FAKE_INSTRUMENT, 101.0, NOW)])

    prices.update_polled([Tick(FAKE_INSTRUMENT, 100.0, NOW - timedelta(seconds=1))])
    assert prices.get(FAKE_INSTRUMENT) == Tick(FAKE_INSTRUMENT, 101.0, NOW)

    later = NOW + timedelta(seconds=15)
    prices.update_polled([Tick(FAKE_INSTRUMENT, 102.0, later)])
    assert prices.get(FAKE_INSTRUMENT) == Tick(FAKE_INSTRUMENT, 102.0, later)
    assert prices.streamed_at(FAKE_INSTRUMENT) == NOW


def test_last_streamed_is_the_newest_live_price_and_ignores_polled_ones() -> None:
    prices = LatestPrices()
    assert prices.last_streamed_at() is None

    prices.update([Tick(FAKE_INSTRUMENT, 101.0, NOW)])
    prices.update_polled([Tick(FAKE_INSTRUMENT, 102.0, NOW + timedelta(seconds=30))])

    assert prices.last_streamed_at() == NOW


def _ist(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, 22, hour, minute, second, tzinfo=EXCHANGE_TIMEZONE)


SESSION = SessionHours(Exchange.NSE, _ist(9).date(), _ist(9, 15), _ist(15, 30), None)


def _fed(
    *ticks: tuple[float, datetime], polled: tuple[float, datetime] | None = None
) -> LatestPrices:
    """FAKE_INSTRUMENT priced by these streamed ticks, oldest first."""
    prices = LatestPrices()
    prices.update(Tick(FAKE_INSTRUMENT, price, at) for price, at in ticks)
    if polled is not None:
        prices.update_polled([Tick(FAKE_INSTRUMENT, polled[0], polled[1])])
    return prices


def test_while_the_feed_streams_the_newest_price_is_current_however_old() -> None:
    # It last traded at 10:00; the feed is alive, so nothing has traded since.
    prices = _fed((100.0, _ist(10)))
    other = Tick(replace(FAKE_INSTRUMENT, symbol="INFY"), 50.0, _ist(11, 59, 55))
    prices.update([other])

    assert prices.current(FAKE_INSTRUMENT, _ist(12), SESSION) == 100.0


def test_a_quiet_feed_in_the_session_leaves_it_to_a_quote() -> None:
    prices = _fed((100.0, _ist(10)))

    assert prices.current(FAKE_INSTRUMENT, _ist(12), SESSION) is None


def test_after_the_close_the_price_from_a_feed_alive_at_the_close_is_final() -> None:
    prices = _fed((100.0, _ist(11)), (101.0, _ist(15, 29, 55)))

    assert prices.current(FAKE_INSTRUMENT, _ist(20), SESSION) == 101.0


def test_after_the_close_a_feed_that_died_in_the_session_says_nothing() -> None:
    prices = _fed((100.0, _ist(11)))

    assert prices.current(FAKE_INSTRUMENT, _ist(20), SESSION) is None


@pytest.mark.parametrize("polled", [False, True])
def test_after_the_close_a_price_received_after_it_is_final(polled: bool) -> None:
    """The feed's first ticks after a restart in the evening, or a quote."""
    late = (99.0, _ist(19))
    prices = _fed(polled=late) if polled else _fed(late)

    assert prices.current(FAKE_INSTRUMENT, _ist(20), SESSION) == 99.0


def test_nothing_known_is_nothing() -> None:
    assert LatestPrices().current(FAKE_INSTRUMENT, _ist(12), SESSION) is None
