"""The order a basket's orders are placed in. Buys go first: a hedged set
(a spread, an iron condor) holds its protection before it sells, and a sell
placed before its hedge would be refused or blocked at the unhedged margin."""

from collections.abc import Sequence

from openticker.ports.models import Side


def basket_sequence(sides: Sequence[Side]) -> list[int]:
    """Indexes into `sides` in placing order: every BUY, then every SELL, each
    in the caller's order."""
    buys = [index for index, side in enumerate(sides) if side is Side.BUY]
    sells = [index for index, side in enumerate(sides) if side is not Side.BUY]
    return buys + sells
