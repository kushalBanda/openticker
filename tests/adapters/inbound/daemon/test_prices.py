from datetime import timedelta

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.ports.models import Tick
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
