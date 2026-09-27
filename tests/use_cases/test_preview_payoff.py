from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest

from openticker.core.options.payoff import PayoffInputError
from openticker.ports.models import Exchange, Instrument, InstrumentType, Quote, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.errors import BatchTooLargeError
from openticker.use_cases.preview_payoff import (
    MAX_PAYOFF_LEGS,
    MixedUnderlyingsError,
    PayoffLegRequest,
    preview_payoff,
)
from tests.fixtures.fake_broker import FAKE_INSTRUMENT, FakeBrokerPort
from tests.fixtures.options import NIFTY_INDEX, chain_contracts, future, option

EXPIRY = date(2026, 9, 29)
NOW = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)
PRICES = {
    "NIFTY 50": 24812.35,
    "NIFTY29SEP2624800CE": 140.0,
    "NIFTY29SEP2624800PE": 128.0,
    "NIFTY29SEP2625400CE": 3.0,
    "NIFTY29SEP2624200PE": 6.0,
    "NIFTY29SEP26FUT": 24851.1,
}


class _Broker(FakeBrokerPort):
    def __init__(self) -> None:
        self.calls = 0

    def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        self.calls += 1
        return [Quote(i, PRICES[i.symbol], NOW) for i in instruments if i.symbol in PRICES]


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments(
        [
            NIFTY_INDEX,
            FAKE_INSTRUMENT,
            future("NIFTY", EXPIRY),
            option("BANKNIFTY", EXPIRY, 53000, InstrumentType.CE),
            *chain_contracts("NIFTY", EXPIRY, [24200, 24800, 25400]),
        ]
    )


def req(symbol: str, side: Side, price: float | None = None, qty: int = 75) -> PayoffLegRequest:
    return PayoffLegRequest(symbol, Exchange.NFO, side, qty, price)


def test_iron_fly_at_the_mock_prices() -> None:
    broker = _Broker()
    legs = [
        req("NIFTY29SEP2624800CE", Side.SELL, 128.05),
        req("NIFTY29SEP2624800PE", Side.SELL, 139.20),
        req("NIFTY29SEP2625400CE", Side.BUY, 3.10),
        req("NIFTY29SEP2624200PE", Side.BUY, 6.15),
    ]

    preview = preview_payoff(legs, broker, NOW)

    assert broker.calls == 1  # the underlying and every leg in one call
    assert preview.underlying.symbol == "NIFTY 50"
    assert preview.spot == 24812.35
    assert preview.payoff.net_premium == 19350.0
    assert preview.payoff.max_loss == -25650.0
    assert preview.payoff.breakevens == (24542.0, 25058.0)
    assert all(leg.implied_volatility for leg in preview.legs)
    assert preview.payoff.points[0].today is not None


def test_uses_quotes_when_price_missing() -> None:
    preview = preview_payoff([req("NIFTY29SEP2624800CE", Side.BUY)], _Broker(), NOW)

    assert preview.legs[0].price == 140.0
    assert preview.payoff.net_premium == -140.0 * 75


def test_a_future_needs_no_volatility() -> None:
    preview = preview_payoff([req("NIFTY29SEP26FUT", Side.SELL)], _Broker(), NOW)

    assert preview.legs[0].implied_volatility is None
    assert preview.payoff.breakevens == (24851.1,)
    assert preview.payoff.max_profit == 24851.1 * 75


def test_mixed_underlyings_refused() -> None:
    legs = [req("NIFTY29SEP2624800CE", Side.BUY), req("BANKNIFTY29SEP2653000CE", Side.SELL)]

    with pytest.raises(MixedUnderlyingsError, match="NIFTY 50, NIFTY BANK"):
        preview_payoff(legs, _Broker(), NOW)


def test_a_stock_is_not_a_leg() -> None:
    with pytest.raises(PayoffInputError, match="only options and futures"):
        preview_payoff(
            [PayoffLegRequest("RELIANCE", Exchange.NSE, Side.BUY, 1, None)], _Broker(), NOW
        )


def test_more_than_20_legs_refused() -> None:
    legs = [req("NIFTY29SEP2624800CE", Side.BUY)] * (MAX_PAYOFF_LEGS + 1)

    with pytest.raises(BatchTooLargeError, match="at most 20"):
        preview_payoff(legs, _Broker(), NOW)
