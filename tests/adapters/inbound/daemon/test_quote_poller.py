from datetime import timedelta

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.inbound.daemon.quote_poller import POLL_EVERY, QuotePoller
from openticker.core.strategies.prices import PriceTimeouts
from openticker.ports.errors import BrokerError, BrokerRateLimitError
from openticker.ports.models import Instrument, Quote, Tick
from openticker.use_cases.strategies.runner import WatchedLeg
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.strategies import NOW


class _Quotes:
    def __init__(self) -> None:
        self.asked: list[list[str]] = []
        self.fail: Exception | None = None

    def __call__(self, broker: str, instruments: list[Instrument]) -> list[Quote]:
        self.asked.append([i.symbol for i in instruments])
        if self.fail is not None:
            raise self.fail
        return [_quote(i) for i in instruments]


def _quote(instrument: Instrument) -> Quote:
    return Quote(instrument, 99.0, NOW)


LEG = WatchedLeg("fake", FAKE_INSTRUMENT, NOW)


def _poller() -> tuple[QuotePoller, _Quotes, LatestPrices]:
    quotes, prices = _Quotes(), LatestPrices()
    return QuotePoller(quotes, prices, PriceTimeouts()), quotes, prices


def test_a_leg_the_feed_is_quiet_on_is_priced_by_a_quote() -> None:
    poller, quotes, prices = _poller()

    poller.poll([LEG], NOW + timedelta(seconds=9))
    assert quotes.asked == []
    later = NOW + timedelta(seconds=11)
    poller.poll([LEG], later)

    assert quotes.asked == [[FAKE_INSTRUMENT.symbol]]
    assert prices.get(FAKE_INSTRUMENT) == Tick(FAKE_INSTRUMENT, 99.0, later)
    assert prices.streamed_at(FAKE_INSTRUMENT) is None


def test_a_streamed_price_takes_the_leg_off_polling() -> None:
    poller, quotes, prices = _poller()
    poller.poll([LEG], NOW + timedelta(seconds=10))

    streamed = NOW + timedelta(seconds=11)
    prices.update([Tick(FAKE_INSTRUMENT, 100.0, streamed)])
    poller.poll([LEG], streamed + POLL_EVERY)

    assert len(quotes.asked) == 1


def test_polls_are_spaced_out() -> None:
    poller, quotes, _ = _poller()
    at = NOW + timedelta(seconds=10)

    poller.poll([LEG], at)
    poller.poll([LEG], at + POLL_EVERY - timedelta(milliseconds=1))
    poller.poll([LEG], at + POLL_EVERY)

    assert len(quotes.asked) == 2


def test_a_rate_limit_pauses_polling_longer_each_time() -> None:
    poller, quotes, prices = _poller()
    quotes.fail = BrokerRateLimitError("slow down")
    at = NOW + timedelta(seconds=10)

    poller.poll([LEG], at)  # limited: pause 2s
    poller.poll([LEG], at + timedelta(seconds=2))  # limited again: pause 5s
    poller.poll([LEG], at + timedelta(seconds=4))  # paused
    poller.poll([LEG], at + timedelta(seconds=7))  # limited a third time: pause 10s
    assert len(quotes.asked) == 3

    quotes.fail = None
    poller.poll([LEG], at + timedelta(seconds=17))  # after the 10s pause
    assert prices.get(FAKE_INSTRUMENT) is not None


def test_a_failed_poll_is_tried_again_next_time() -> None:
    poller, quotes, prices = _poller()
    quotes.fail = BrokerError("Kite /quote failed: HTTP 500")
    at = NOW + timedelta(seconds=10)

    poller.poll([LEG], at)
    quotes.fail = None
    poller.poll([LEG], at + POLL_EVERY)

    assert len(quotes.asked) == 2 and prices.get(FAKE_INSTRUMENT) is not None


def test_a_good_poll_resets_the_rate_limit_pause() -> None:
    poller, quotes, _ = _poller()
    at = NOW + timedelta(seconds=10)
    quotes.fail = BrokerRateLimitError("slow down")
    poller.poll([LEG], at)  # pause 2s
    poller.poll([LEG], at + timedelta(seconds=2))  # pause 5s
    quotes.fail = None
    poller.poll([LEG], at + timedelta(seconds=7))  # a good one

    quotes.fail = BrokerRateLimitError("slow down")
    poller.poll([LEG], at + timedelta(seconds=9))  # pause 2s again, not 10s
    poller.poll([LEG], at + timedelta(seconds=11))

    assert len(quotes.asked) == 5


def test_a_network_failure_never_escapes_the_poller() -> None:
    import httpx

    poller, quotes, prices = _poller()
    quotes.fail = httpx.ConnectError("network down")
    at = NOW + timedelta(seconds=10)

    poller.poll([LEG], at)  # logged, not raised: the runs must still be stepped
    quotes.fail = None
    poller.poll([LEG], at + POLL_EVERY)

    assert prices.get(FAKE_INSTRUMENT) is not None
