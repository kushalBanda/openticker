"""Whether the shipped charge rates still match the broker's. Pure (ADR 28 in
docs/adr).

A few sample orders, one per segment and side, are priced twice: by our
rates and by the broker's own contract note. Any figure that differs by
more than a paisa is reported with both amounts, so the rates file can be
corrected from the report alone.

Kite decides that a trade is intraday by matching a buy against a sell of
the same contract on the same day, not by its product: an MIS buy sent on
its own is charged as delivery. So an intraday sample goes as a buy and a
sell together, and every other request holds no two orders for the same
contract.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from openticker.core.orders.charges import Charges, Segment, segment_of
from openticker.ports.models import Instrument, Product, Side

# Both sides round each figure to the paisa.
TOLERANCE = 0.01


@dataclass(frozen=True)
class ChargeSample:
    """An order as executed: what the broker's contract note is asked to price."""

    instrument: Instrument
    side: Side
    quantity: int
    product: Product
    price: float

    @property
    def segment(self) -> Segment:
        return segment_of(self.instrument, self.product)


@dataclass(frozen=True)
class ChargeDifference:
    key: str  # a charge's key, "gst" or "total"
    ours: float
    broker: float


def differences(ours: Charges, broker: Charges) -> tuple[ChargeDifference, ...]:
    """Every item, and the total, that differs by more than TOLERANCE. An item
    only one side charges counts as 0 on the other."""
    keys = list(ours.items) + [key for key in broker.items if key not in ours.items]
    found = [
        ChargeDifference(key, ours.items.get(key, 0.0), broker.items.get(key, 0.0)) for key in keys
    ]
    found.append(ChargeDifference("total", ours.total, broker.total))
    return tuple(d for d in found if round(abs(d.ours - d.broker), 2) > TOLERANCE)


def broker_requests(samples: Sequence[ChargeSample]) -> list[tuple[ChargeSample, ...]]:
    """Samples grouped into contract-note requests: each intraday contract's
    buy and sell together, so they net as a round trip; every other buy in
    one request and every other sell in another, so none of them net."""
    intraday: dict[tuple[str, str], list[ChargeSample]] = {}
    buys: list[ChargeSample] = []
    sells: list[ChargeSample] = []
    for sample in samples:
        if sample.segment is Segment.EQUITY_INTRADAY:
            contract = (sample.instrument.exchange.value, sample.instrument.symbol)
            intraday.setdefault(contract, []).append(sample)
        elif sample.side is Side.BUY:
            buys.append(sample)
        else:
            sells.append(sample)
    groups = [tuple(buys), tuple(sells), *(tuple(pair) for pair in intraday.values())]
    return [group for group in groups if group]
