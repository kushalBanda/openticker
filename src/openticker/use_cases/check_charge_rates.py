"""Checks the charge rates the sandbox pays against the broker's own contract
note (ADR 28 in docs/adr). The daemon runs it once a day; an agent can run it
any time. Nothing is placed, and no fill ever waits on it.

The samples are one buy and one sell per segment the rates cover, at the
contract's last price: RELIANCE for equity, and for index derivatives the
nearest future and the call nearest to that future's price. A sample that
can't be found (instruments not synced, no price) is skipped and says why;
a segment with no sample rule, like a commodity schedule added to an
override file, is skipped too.
"""

from dataclasses import dataclass
from datetime import date, datetime

from openticker.core.orders.charge_check import (
    ChargeDifference,
    ChargeSample,
    broker_requests,
    differences,
)
from openticker.core.orders.charges import ChargeBook, Charges, ChargeSchedule, Segment, charges_for
from openticker.events.bus import EventPublisher
from openticker.events.types import ChargeRatesDiffer
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import (
    EXCHANGE_TIMEZONE,
    Exchange,
    Instrument,
    InstrumentType,
    Product,
    Side,
)
from openticker.storage.charges_file import load_charge_book
from openticker.storage.sqlite.instruments_repo import (
    future_contracts,
    get_instrument,
    option_contracts,
    option_expiries,
)

EQUITY_SAMPLE = "RELIANCE"
EQUITY_QUANTITY = 10
INDEX_SAMPLES = {Exchange.NFO: "NIFTY", Exchange.BFO: "SENSEX"}  # one lot each


class NoChargeSamplesError(LookupError):
    pass


@dataclass(frozen=True)
class SampleCheck:
    sample: ChargeSample
    ours: Charges
    broker: Charges
    differences: tuple[ChargeDifference, ...]


@dataclass(frozen=True)
class ChargeRateCheck:
    broker: str
    checked_at: datetime
    rates_source: str
    rates_as_of: date  # the oldest schedule's date
    samples: tuple[SampleCheck, ...]
    skipped: tuple[str, ...]  # "<segment> on <exchange>: <why>"

    @property
    def differing(self) -> tuple[SampleCheck, ...]:
        return tuple(check for check in self.samples if check.differences)


@dataclass(frozen=True)
class _Wanted:
    schedule: ChargeSchedule
    instrument: Instrument
    product: Product
    quantity: int


def check_charge_rates(
    broker_name: str,
    broker: BrokerPort,
    events: EventPublisher,
    now: datetime,
    triggered_by: str,
) -> ChargeRateCheck:
    book = load_charge_book()
    samples, skipped = _samples(book, broker, now.astimezone(EXCHANGE_TIMEZONE).date())
    if not samples:
        raise NoChargeSamplesError(
            "no sample contract could be priced: " + "; ".join(skipped)
            if skipped
            else "the charge rates cover no segment"
        )
    priced: dict[ChargeSample, Charges] = {}
    for request in broker_requests(samples):
        priced.update(zip(request, broker.get_charges(request), strict=True))
    checks = []
    for sample in samples:
        schedule = book.for_fill(sample.instrument, sample.product)
        assert schedule is not None  # every sample comes from a schedule
        ours = charges_for(schedule, sample.side, sample.quantity, sample.price)
        checks.append(SampleCheck(sample, ours, priced[sample], differences(ours, priced[sample])))
    schedules = list(book.schedules.values())
    result = ChargeRateCheck(
        broker=broker_name,
        checked_at=now,
        rates_source=schedules[0].source,
        rates_as_of=min(schedule.as_of for schedule in schedules),
        samples=tuple(checks),
        skipped=tuple(skipped),
    )
    if result.differing:
        events.publish(
            ChargeRatesDiffer(
                broker=broker_name,
                rates_as_of=result.rates_as_of.isoformat(),
                differing=len(result.differing),
                checked=len(result.samples),
                detail="; ".join(_describe(check) for check in result.differing),
                triggered_by=triggered_by,
            )
        )
    return result


def _describe(check: SampleCheck) -> str:
    sample = check.sample
    figures = ", ".join(
        f"{d.key} ours {d.ours:,.2f}, broker {d.broker:,.2f}" for d in check.differences
    )
    return (
        f"{sample.segment} {sample.side} {sample.quantity} {sample.instrument.symbol} "
        f"({sample.instrument.exchange}) @ {sample.price:,.2f}: {figures}"
    )


def _samples(
    book: ChargeBook, broker: BrokerPort, today: date
) -> tuple[list[ChargeSample], list[str]]:
    wanted: list[_Wanted] = []
    skipped: list[str] = []
    options: list[ChargeSchedule] = []
    for (segment, exchange), schedule in sorted(book.schedules.items()):
        where = f"{segment} on {exchange}"
        match segment:
            case Segment.EQUITY_DELIVERY | Segment.EQUITY_INTRADAY:
                instrument = get_instrument(EQUITY_SAMPLE, exchange.value)
                product = Product.CNC if segment is Segment.EQUITY_DELIVERY else Product.MIS
                if instrument is None:
                    skipped.append(f"{where}: {EQUITY_SAMPLE} is not in the instrument list")
                else:
                    wanted.append(_Wanted(schedule, instrument, product, EQUITY_QUANTITY))
            case Segment.FUTURES if exchange in INDEX_SAMPLES:
                future = _nearest_future(exchange, today)
                if future is None:
                    skipped.append(f"{where}: no {INDEX_SAMPLES[exchange]} future listed")
                else:
                    wanted.append(_Wanted(schedule, future, Product.NRML, future.lot_size))
            case Segment.OPTIONS if exchange in INDEX_SAMPLES:
                options.append(schedule)
            case _:
                skipped.append(f"{where}: no sample contract for this segment")

    # An option sample is the call nearest its index future's price.
    references = {
        schedule.exchange: _nearest_future(schedule.exchange, today) for schedule in options
    }
    prices = _last_prices(
        broker,
        [w.instrument for w in wanted] + [f for f in references.values() if f is not None],
    )
    for schedule in options:
        where = f"{schedule.segment} on {schedule.exchange}"
        future = references[schedule.exchange]
        call = _call_near(schedule.exchange, today, prices.get(future)) if future else None
        if call is None:
            skipped.append(f"{where}: no {INDEX_SAMPLES[schedule.exchange]} option priced")
        else:
            wanted.append(_Wanted(schedule, call, Product.NRML, call.lot_size))
    prices.update(
        _last_prices(broker, [w.instrument for w in wanted if w.instrument not in prices])
    )

    samples: list[ChargeSample] = []
    for w in wanted:
        price = prices.get(w.instrument)
        if price is None:
            skipped.append(
                f"{w.schedule.segment} on {w.schedule.exchange}: "
                f"no last price for {w.instrument.symbol}"
            )
            continue
        samples += [
            ChargeSample(w.instrument, side, w.quantity, w.product, price)
            for side in (Side.BUY, Side.SELL)
        ]
    return samples, skipped


def _nearest_future(exchange: Exchange, today: date) -> Instrument | None:
    futures = future_contracts(INDEX_SAMPLES[exchange], exchange.value, today)
    return futures[0] if futures else None


def _call_near(exchange: Exchange, today: date, price: float | None) -> Instrument | None:
    name = INDEX_SAMPLES[exchange]
    expiries = option_expiries(name, exchange.value, today)
    if price is None or not expiries:
        return None
    calls = [
        contract
        for contract in option_contracts(name, exchange.value, expiries[0])
        if contract.instrument_type is InstrumentType.CE and contract.strike is not None
    ]
    return min(calls, key=lambda c: abs((c.strike or 0.0) - price), default=None)


def _last_prices(broker: BrokerPort, instruments: list[Instrument]) -> dict[Instrument, float]:
    if not instruments:
        return {}
    return {
        quote.instrument: quote.last_price
        for quote in broker.get_quotes(list(dict.fromkeys(instruments)))
        if quote.last_price > 0
    }
