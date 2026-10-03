import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from importlib.resources import files

import pytest

from openticker.core.orders.charge_check import ChargeSample
from openticker.core.orders.charges import Charges
from openticker.events.types import ChargeRatesChecked, ChargeRatesDiffer
from openticker.ports.models import Exchange, Product, Side
from openticker.storage.sqlite.engine import get_data_dir
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.check_charge_rates import NoChargeSamplesError, check_charge_rates
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.options import chain_contracts, future
from tests.fixtures.priced_broker import PricedBroker

NOW = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST
NEAR, NEXT = date(2026, 9, 29), date(2026, 10, 27)
NIFTY_FUTURE = future("NIFTY", NEAR)
SENSEX_FUTURE = future("SENSEX", NEAR, Exchange.BFO)
MARKET = [
    FAKE_INSTRUMENT,
    replace(FAKE_INSTRUMENT, exchange=Exchange.BSE, broker_exchange="BSE", token="bse-1"),
    NIFTY_FUTURE,
    future("NIFTY", NEXT),
    *chain_contracts("NIFTY", NEAR, [24900, 25000, 25100]),
    *chain_contracts("NIFTY", NEXT, [25000]),
    SENSEX_FUTURE,
    *chain_contracts("SENSEX", NEAR, [81900, 82000], Exchange.BFO),
]


class _Events:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


class _Broker(PricedBroker):
    """Records each contract-note request; `extra` is added to one item of
    the samples whose symbol it names."""

    def __init__(self) -> None:
        super().__init__(100.0)
        self.prices = {NIFTY_FUTURE.symbol: 25040.0, SENSEX_FUTURE.symbol: 81980.0}
        self.requests: list[list[ChargeSample]] = []
        self.extra: dict[tuple[str, Side], tuple[str, float]] = {}

    def get_charges(self, orders: Sequence[ChargeSample]) -> list[Charges]:
        self.requests.append(list(orders))
        charged = super().get_charges(orders)
        for index, order in enumerate(orders):
            if (order.instrument.symbol, order.side) in self.extra:
                key, amount = self.extra[(order.instrument.symbol, order.side)]
                items = dict(charged[index].items)
                items[key] += amount
                charged[index] = Charges(items)
        return charged


def test_every_segment_is_sampled_both_ways_and_agrees() -> None:
    upsert_instruments(MARKET)
    broker, events = _Broker(), _Events()

    result = check_charge_rates("fake", broker, events, NOW, "mcp")

    sampled = {
        (s.sample.segment, s.sample.instrument.exchange, s.sample.instrument.symbol)
        for s in result.samples
    }
    assert sampled == {
        ("equity_delivery", Exchange.NSE, "RELIANCE"),
        ("equity_delivery", Exchange.BSE, "RELIANCE"),
        ("equity_intraday", Exchange.NSE, "RELIANCE"),
        ("equity_intraday", Exchange.BSE, "RELIANCE"),
        ("futures", Exchange.NFO, "NIFTY29SEP26FUT"),  # the nearest future
        ("futures", Exchange.BFO, "SENSEX29SEP26FUT"),
        ("options", Exchange.NFO, "NIFTY29SEP2625000CE"),  # the call nearest 25,040
        ("options", Exchange.BFO, "SENSEX29SEP2682000CE"),
    }
    assert len(result.samples) == 16  # a buy and a sell each
    assert {s.sample.quantity for s in result.samples if s.sample.instrument.lot_size == 65} == {65}
    assert result.differing == () and result.skipped == ()
    [checked] = events.events  # a check that finds nothing is still recorded, not notified
    assert isinstance(checked, ChargeRatesChecked)
    assert (checked.differing, checked.checked, checked.skipped) == (0, 16, 0)
    assert result.rates_as_of == date(2026, 9, 25)


def test_only_intraday_samples_share_a_request_with_their_other_side() -> None:
    upsert_instruments(MARKET)
    broker = _Broker()

    check_charge_rates("fake", broker, _Events(), NOW, "mcp")

    for request in broker.requests:
        contracts = [(o.instrument.exchange, o.instrument.symbol, o.product) for o in request]
        if len(set(contracts)) < len(contracts):
            assert {o.product for o in request} == {Product.MIS} and len(request) == 2
    assert len(broker.requests) == 4  # every buy, every sell, and one pair per exchange's MIS


def test_a_differing_figure_is_notified_with_both_amounts() -> None:
    upsert_instruments(MARKET)
    broker, events = _Broker(), _Events()
    broker.extra[("NIFTY29SEP2625000CE", Side.SELL)] = ("transaction_tax", 1.5)

    result = check_charge_rates("fake", broker, events, NOW, "daemon")

    [differing] = result.differing
    assert (differing.sample.instrument.symbol, differing.sample.side) == (
        "NIFTY29SEP2625000CE",
        Side.SELL,
    )
    tax = differing.ours.items["transaction_tax"]
    [checked, event] = events.events
    assert isinstance(checked, ChargeRatesChecked) and checked.differing == 1
    assert isinstance(event, ChargeRatesDiffer)
    assert (event.broker, event.differing, event.checked, event.triggered_by) == (
        "fake",
        1,
        16,
        "daemon",
    )
    assert f"transaction_tax ours {tax:,.2f}, broker {tax + 1.5:,.2f}" in event.detail
    assert "options SELL 65 NIFTY29SEP2625000CE (NFO)" in event.detail
    assert event.rates_as_of == "2026-09-25"


def test_contracts_not_listed_or_not_priced_are_skipped_with_why() -> None:
    upsert_instruments([FAKE_INSTRUMENT, NIFTY_FUTURE, SENSEX_FUTURE])
    broker = _Broker()
    broker.prices[SENSEX_FUTURE.symbol] = 0.0  # no trade yet

    result = check_charge_rates("fake", broker, _Events(), NOW, "mcp")

    assert {s.sample.instrument.symbol for s in result.samples} == {"RELIANCE", NIFTY_FUTURE.symbol}
    assert sorted(result.skipped) == [
        "equity_delivery on BSE: RELIANCE is not in the instrument list",
        "equity_intraday on BSE: RELIANCE is not in the instrument list",
        "futures on BFO: no last price for SENSEX29SEP26FUT",
        "options on BFO: no SENSEX option priced",
        "options on NFO: no NIFTY option priced",
    ]


def test_with_nothing_to_price_it_says_why() -> None:
    with pytest.raises(NoChargeSamplesError, match="RELIANCE is not in the instrument list"):
        check_charge_rates("fake", _Broker(), _Events(), NOW, "mcp")


def test_a_segment_with_no_sample_rule_is_skipped() -> None:
    shipped = json.loads(files("openticker").joinpath("data/charges.json").read_text())
    mcx = {**shipped["schedules"][0], "segment": "commodity_futures", "exchange": "MCX"}
    shipped["schedules"].append(mcx)
    (get_data_dir() / "charges.json").write_text(json.dumps(shipped))
    upsert_instruments(MARKET)

    result = check_charge_rates("fake", _Broker(), _Events(), NOW, "mcp")

    assert result.skipped == ("commodity_futures on MCX: no sample contract for this segment",)
