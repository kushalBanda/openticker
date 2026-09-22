"""validate_order: is this order well formed for this instrument? Shape and
limits only; whether it is wise is core/risk's question."""

from datetime import date

from openticker.core.orders.models import OrderRequest, OrderType, ValidationResult
from openticker.ports.models import InstrumentType, Product

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
    if request.order_type is not OrderType.MARKET:
        return _invalid(f"{request.order_type} orders are not supported yet; use MARKET")
    if request.price is not None:
        return _invalid("MARKET orders take no price")
    return ValidationResult(valid=True, reason=None)


def _invalid(reason: str) -> ValidationResult:
    return ValidationResult(valid=False, reason=reason)
