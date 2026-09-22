"""validate_order: is this order well formed for this instrument? Shape and
limits only; whether it is wise is core/risk's question."""

from datetime import date

from openticker.core.orders.models import OrderRequest, OrderType, ValidationResult
from openticker.ports.models import InstrumentType, Product, Side

_PRODUCTS: dict[InstrumentType, tuple[Product, ...]] = {
    InstrumentType.EQ: (Product.CNC, Product.MIS),
    InstrumentType.FUT: (Product.NRML, Product.MIS),
    InstrumentType.CE: (Product.NRML, Product.MIS),
    InstrumentType.PE: (Product.NRML, Product.MIS),
}


def validate_order(request: OrderRequest, today: date) -> ValidationResult:
    """`today` is the exchange-local trading date."""
    instrument = request.instrument
    allowed = _PRODUCTS.get(instrument.instrument_type)
    if allowed is None:
        return _invalid(
            f"{instrument.symbol} is an index and can't be traded; trade its futures or options"
        )
    if instrument.expiry is not None and instrument.expiry < today:
        return _invalid(f"{instrument.symbol} expired on {instrument.expiry}")
    if request.quantity <= 0:
        return _invalid(f"quantity must be positive, got {request.quantity}")
    lot = instrument.lot_size if instrument.lot_size > 0 else 1
    if request.quantity % lot:
        return _invalid(
            f"quantity {request.quantity} is not a multiple of the lot size {lot} for "
            f"{instrument.symbol}"
        )
    if request.product not in allowed:
        return _invalid(
            f"{request.product} isn't available for {instrument.instrument_type}; use "
            f"{' or '.join(allowed)}"
        )
    return _prices(request)


def _prices(request: OrderRequest) -> ValidationResult:
    """Which prices each order type takes, on the instrument's tick size. An
    SL order's limit is at or beyond its trigger, in the direction it trades."""
    kind, price, trigger = request.order_type, request.price, request.trigger_price
    needs_price = kind in (OrderType.LIMIT, OrderType.SL)
    needs_trigger = kind in (OrderType.SL, OrderType.SL_M)
    if needs_price != (price is not None):
        return _invalid(
            f"{kind} orders need a price" if needs_price else f"{kind} orders take no price"
        )
    if needs_trigger != (trigger is not None):
        return _invalid(
            f"{kind} orders need a trigger_price"
            if needs_trigger
            else f"{kind} orders take no trigger_price"
        )
    tick = request.instrument.tick_size
    for name, value in (("price", price), ("trigger_price", trigger)):
        if value is None:
            continue
        if value <= 0:
            return _invalid(f"{name} must be positive, got {value}")
        if tick > 0 and abs(round(value / tick) * tick - value) > 1e-9:
            return _invalid(f"{name} {value} is not a multiple of the tick size {tick}")
    if kind is OrderType.SL and price is not None and trigger is not None:
        buying = request.side is Side.BUY
        if (price < trigger) if buying else (price > trigger):
            return _invalid(
                f"an SL {request.side} order's price must be at or "
                f"{'above' if buying else 'below'} its trigger_price"
            )
    return ValidationResult(valid=True, reason=None)


def _invalid(reason: str) -> ValidationResult:
    return ValidationResult(valid=False, reason=reason)
