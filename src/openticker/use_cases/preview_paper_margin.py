"""The margin the paper account would block for an order (ADR 11 in docs/adr):
the sandbox's own rule, net of the position it adds to or closes. The
broker's own figure is get_margin (ADR 26)."""

from openticker.core.orders.sandbox import PaperMargin
from openticker.ports.models import Exchange, Product, Side
from openticker.ports.sandbox_port import OrderSandbox
from openticker.use_cases.resolve_instrument import resolve_instrument


def preview_paper_margin(
    sandbox: OrderSandbox,
    symbol: str,
    exchange: Exchange,
    side: Side,
    quantity: int,
    product: Product,
    price: float,
) -> PaperMargin:
    instrument = resolve_instrument(symbol, exchange.value)
    return sandbox.preview_margin(instrument, side, quantity, product, price)
