"""What a paper fill of an order would pay in brokerage, taxes and exchange
fees, from the same rates the sandbox charges (ADR 28 in docs/adr). Local:
nothing is sent to the broker."""

from dataclasses import dataclass

from openticker.core.orders.charges import Charges, ChargeSchedule, charges_for
from openticker.ports.models import Exchange, Product, Side
from openticker.storage.charges_file import load_charge_book
from openticker.use_cases.resolve_instrument import resolve_instrument


class ChargesNotModelledError(LookupError):
    pass


@dataclass(frozen=True)
class ChargePreview:
    schedule: ChargeSchedule
    charges: Charges


def preview_charges(
    symbol: str, exchange: Exchange, side: Side, quantity: int, price: float, product: Product
) -> ChargePreview:
    instrument = resolve_instrument(symbol, exchange.value)
    schedule = load_charge_book().for_fill(instrument, product)
    if schedule is None:
        raise ChargesNotModelledError(
            f"charges for {instrument.symbol} on {instrument.exchange} are not modelled: "
            "its fills are recorded without charges"
        )
    return ChargePreview(schedule, charges_for(schedule, side, quantity, price))
