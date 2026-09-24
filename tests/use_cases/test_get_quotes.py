from collections.abc import Sequence
from dataclasses import replace

import pytest

from openticker.ports.models import Instrument, Quote
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.errors import BatchTooLargeError
from openticker.use_cases.get_quotes import MAX_QUOTES, NO_QUOTE, get_quotes
from openticker.use_cases.resolve_instrument import UnknownInstrumentError
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker

TCS = replace(FAKE_INSTRUMENT, symbol="TCS", broker_symbol="TCS", token="fake-2")
ILLIQUID = replace(FAKE_INSTRUMENT, symbol="ILLIQUID", broker_symbol="ILLIQUID", token="fake-3")


class _Counting(PricedBroker):
    """Quotes everything but ILLIQUID, and counts broker calls."""

    def __init__(self) -> None:
        super().__init__(100.0)
        self.calls: list[list[str]] = []

    def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        self.calls.append([instrument.symbol for instrument in instruments])
        return [
            self.get_quote(instrument)
            for instrument in reversed(instruments)  # brokers don't promise an order
            if instrument.symbol != "ILLIQUID"
        ]


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT, TCS, ILLIQUID])


def test_one_broker_call_answers_in_the_order_asked_repeats_once() -> None:
    broker = _Counting()

    lookup = get_quotes(broker, [("TCS", "NSE"), ("RELIANCE", "NSE"), ("TCS", "NSE")])

    assert broker.calls == [["TCS", "RELIANCE"]]
    assert [quote.instrument.symbol for quote in lookup.quotes] == ["TCS", "RELIANCE"]
    assert lookup.missing == []


def test_unknown_and_unquoted_are_listed_with_why() -> None:
    lookup = get_quotes(_Counting(), [("ILLIQUID", "NSE"), ("NOPE", "NSE"), ("RELIANCE", "NSE")])

    assert [quote.instrument.symbol for quote in lookup.quotes] == ["RELIANCE"]
    assert [(m.symbol, m.exchange) for m in lookup.missing] == [
        ("NOPE", "NSE"),
        ("ILLIQUID", "NSE"),
    ]
    assert "sync_instruments" in lookup.missing[0].reason
    assert lookup.missing[1].reason == NO_QUOTE


def test_nothing_known_fails_without_a_broker_call() -> None:
    broker = _Counting()

    with pytest.raises(UnknownInstrumentError, match="'NOPE'"):
        get_quotes(broker, [("NOPE", "NSE"), ("ALSO", "NSE")])
    assert broker.calls == []


def test_more_than_the_limit_is_refused() -> None:
    wanted = [(f"S{i}", "NSE") for i in range(MAX_QUOTES + 1)]

    with pytest.raises(BatchTooLargeError, match="at most 50"):
        get_quotes(_Counting(), wanted)
