"""What an executed paper order pays in brokerage, taxes and fees. Pure
(ADR 28 in docs/adr).

A schedule is a list of rules, not a fixed set of Indian taxes: each rule
says what it is charged on and whether GST applies to it, the way OpenAlgo's
portfolio cost model does. Four bases cover every charge: `turnover` (the
order's value, either side), `buy` or `sell` (that side only, like stamp
duty or STT), and `order` (a flat amount, or a rate capped per order, which
is how discount brokerage works). The value of an option order is its
premium.

Rates live in a data file with their source and date, so a new budget's
STT is a data change, not a code change.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from openticker.ports.models import Exchange, Instrument, InstrumentType, Product, Side


class ChargeBookError(ValueError):
    pass


class Basis(StrEnum):
    TURNOVER = "turnover"
    BUY = "buy"
    SELL = "sell"
    ORDER = "order"


class Segment(StrEnum):
    EQUITY_DELIVERY = "equity_delivery"
    EQUITY_INTRADAY = "equity_intraday"
    FUTURES = "futures"
    OPTIONS = "options"
    COMMODITY_FUTURES = "commodity_futures"
    COMMODITY_OPTIONS = "commodity_options"


@dataclass(frozen=True)
class Charge:
    key: str  # brokerage, transaction_tax (STT or CTT), exchange_txn, sebi, stamp_duty
    basis: Basis
    rate: float = 0.0  # a fraction of the value on its basis
    flat: float = 0.0  # `order` basis: a flat amount per order
    cap: float | None = None  # `order` basis: rate × value, at most this per order
    taxed: bool = False  # GST applies
    rounded: bool = False  # to the nearest rupee, as stamp duty is

    def amount(self, side: Side, value: float) -> float:
        raw = self._raw(side, value)
        return math.floor(raw + 0.5) if self.rounded else raw

    def _raw(self, side: Side, value: float) -> float:
        match self.basis:
            case Basis.TURNOVER:
                return value * self.rate
            case Basis.BUY:
                return value * self.rate if side is Side.BUY else 0.0
            case Basis.SELL:
                return value * self.rate if side is Side.SELL else 0.0
            case Basis.ORDER:
                charged = self.flat + value * self.rate
                return min(charged, self.cap) if self.cap is not None else charged


@dataclass(frozen=True)
class ChargeSchedule:
    segment: Segment
    exchange: Exchange
    gst_rate: float
    charges: tuple[Charge, ...]
    source: str
    as_of: date


@dataclass(frozen=True)
class Charges:
    items: Mapping[str, float]  # each charge's key, and "gst"

    @property
    def total(self) -> float:
        return round(sum(self.items.values()), 2)


def charges_for(schedule: ChargeSchedule, side: Side, quantity: int, price: float) -> Charges:
    value = quantity * price
    items: dict[str, float] = {}
    taxable = 0.0
    for charge in schedule.charges:
        amount = charge.amount(side, value)
        items[charge.key] = round(amount, 2)
        if charge.taxed:
            taxable += amount
    items["gst"] = round(taxable * schedule.gst_rate, 2)
    return Charges(items=items)


def segment_of(instrument: Instrument, product: Product) -> Segment:
    commodity = instrument.exchange is Exchange.MCX
    match instrument.instrument_type:
        case InstrumentType.EQ:
            return Segment.EQUITY_DELIVERY if product is Product.CNC else Segment.EQUITY_INTRADAY
        case InstrumentType.FUT:
            return Segment.COMMODITY_FUTURES if commodity else Segment.FUTURES
        case InstrumentType.CE | InstrumentType.PE:
            return Segment.COMMODITY_OPTIONS if commodity else Segment.OPTIONS
    raise ValueError(f"{instrument.symbol} ({instrument.instrument_type}) is not tradeable")


@dataclass(frozen=True)
class ChargeBook:
    schedules: Mapping[tuple[Segment, Exchange], ChargeSchedule]

    def for_fill(self, instrument: Instrument, product: Product) -> ChargeSchedule | None:
        """None when the book has no schedule for it: the fill is then
        recorded without charges, as it was before costs were modelled."""
        return self.schedules.get((segment_of(instrument, product), instrument.exchange))


def parse_charge_book(data: Mapping[str, Any]) -> ChargeBook:
    """From the charges file's JSON. Raises ChargeBookError naming the bad entry."""
    try:
        source = str(data["source"])
        as_of = date.fromisoformat(str(data["as_of"]))
        gst_rate = _fraction(data["gst_rate"], "gst_rate")
        entries = list(data["schedules"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ChargeBookError(f"the file's header: {exc}") from exc
    schedules: dict[tuple[Segment, Exchange], ChargeSchedule] = {}
    for index, entry in enumerate(entries):
        where = f"schedules[{index}]"
        try:
            schedule = ChargeSchedule(
                segment=Segment(entry["segment"]),
                exchange=Exchange(entry["exchange"]),
                gst_rate=gst_rate,
                charges=tuple(_charge(item) for item in entry["charges"]),
                source=source,
                as_of=as_of,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ChargeBookError(f"{where}: {exc}") from exc
        key = (schedule.segment, schedule.exchange)
        if key in schedules:
            raise ChargeBookError(f"{where}: {key[0]} on {key[1]} is listed twice")
        schedules[key] = schedule
    return ChargeBook(schedules=schedules)


def _charge(item: Mapping[str, Any]) -> Charge:
    key = str(item["key"])
    cap = item.get("cap")
    return Charge(
        key=key,
        basis=Basis(item["basis"]),
        rate=_fraction(item.get("rate", 0.0), key),
        flat=_amount(item.get("flat", 0.0), key),
        cap=None if cap is None else _amount(cap, key),
        taxed=bool(item.get("taxed", False)),
        rounded=bool(item.get("rounded", False)),
    )


def _fraction(value: object, name: str) -> float:
    number = _amount(value, name)
    if number >= 1:
        raise ValueError(f"{name}: a rate is a fraction below 1, got {number}")
    return number


def _amount(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name}: expected a number, got {value!r}")
    number = float(value)
    if not (math.isfinite(number) and number >= 0):
        raise ValueError(f"{name}: expected a non-negative number, got {number}")
    return number
