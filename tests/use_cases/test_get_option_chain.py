from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from openticker.core.options.chain import years_to_expiry
from openticker.core.options.greeks import black76_price
from openticker.ports.models import Instrument, InstrumentType, Quote
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.get_option_chain import NoOptionsError, get_option_chain
from tests.fixtures.fake_broker import FakeBrokerPort
from tests.fixtures.options import NIFTY_INDEX, chain_contracts, future

THIS_WEEK, NEXT_WEEK = date(2026, 9, 22), date(2026, 9, 29)
MORNING = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)  # 09:30 IST on THIS_WEEK's expiry day
AFTER_CLOSE = datetime(2026, 9, 22, 10, 30, tzinfo=UTC)  # 16:00 IST
STRIKES = [float(strike) for strike in range(24500, 25600, 100)]


class _ChainBroker(FakeBrokerPort):
    """NIFTY 50 at `spot`; options priced by Black-76 at a flat 15% off `forward`."""

    def __init__(self, spot: float = 25030.0, forward: float = 25080.0) -> None:
        self.spot, self.forward = spot, forward
        self.quoted: list[str] = []

    def get_quote(self, instrument: Instrument) -> Quote:
        return Quote(instrument, self.spot, MORNING)

    def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        self.quoted.extend(instrument.symbol for instrument in instruments)
        return [
            Quote(instrument, self.forward, MORNING)
            if instrument.instrument_type is InstrumentType.FUT
            else Quote(
                instrument,
                black76_price(
                    instrument.instrument_type,
                    self.forward,
                    instrument.strike or 0,
                    years_to_expiry(instrument.expiry or THIS_WEEK, MORNING),
                    0.0,
                    0.15,
                ),
                MORNING,
                open_interest=10,
            )
            for instrument in instruments
        ]


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments(
        [NIFTY_INDEX]
        + chain_contracts("NIFTY", THIS_WEEK, STRIKES)
        + chain_contracts("NIFTY", NEXT_WEEK, STRIKES)
    )


def test_nearest_expiry_and_strikes_around_atm_only_are_quoted() -> None:
    broker = _ChainBroker()

    chain, expiries = get_option_chain(broker, "NIFTY 50", "NSE", None, 2, 0.0, MORNING)

    assert expiries == [THIS_WEEK, NEXT_WEEK]
    assert chain.expiry == THIS_WEEK
    assert chain.atm_strike == 25000
    assert [row.strike for row in chain.rows] == [24800, 24900, 25000, 25100, 25200]
    assert len(broker.quoted) == 10
    assert chain.forward_price == pytest.approx(25080)


def test_expiry_day_after_the_close_moves_to_the_next_expiry() -> None:
    chain, expiries = get_option_chain(_ChainBroker(), "NIFTY 50", "NSE", None, 1, 0.0, AFTER_CLOSE)

    assert expiries == [NEXT_WEEK]
    assert chain.expiry == NEXT_WEEK


def test_unknown_expiry_lists_the_available_ones() -> None:
    with pytest.raises(NoOptionsError, match="2026-09-22, 2026-09-29"):
        get_option_chain(_ChainBroker(), "NIFTY 50", "NSE", date(2026, 9, 24), 1, 0.0, MORNING)


def test_underlying_with_no_synced_options_says_to_sync() -> None:
    upsert_instruments([replace(NIFTY_INDEX, symbol="NIFTY BANK")])

    with pytest.raises(NoOptionsError, match="sync_instruments"):
        get_option_chain(_ChainBroker(), "NIFTY BANK", "NSE", None, 1, 0.0, MORNING)


def test_nearest_two_futures_come_in_the_same_quote_call_with_the_book() -> None:
    upsert_instruments(
        [
            future("NIFTY", THIS_WEEK),  # expires at 15:30 today: shown this morning
            future("NIFTY", NEXT_WEEK),
            future("NIFTY", date(2026, 10, 27)),
            future("NIFTYNXT50", NEXT_WEEK),  # another underlying
        ]
    )

    class _Booked(_ChainBroker):
        def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
            quotes = super().get_quotes(instruments)
            return [replace(q, bid=q.last_price - 0.5, ask=0.0) for q in quotes]

    broker = _Booked()
    chain, _ = get_option_chain(broker, "NIFTY 50", "NSE", None, 1, 0.0, MORNING)

    assert [q.instrument.symbol for q in chain.futures] == ["NIFTY22SEP26FUT", "NIFTY29SEP26FUT"]
    assert len(broker.quoted) == 6 + 2  # one call
    call = chain.rows[1].call
    assert call is not None and call.last_price is not None
    assert call.bid == pytest.approx(call.last_price - 0.5)
    assert call.ask is None  # an empty side comes as 0
