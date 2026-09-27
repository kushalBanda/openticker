"""Which instruments the daemon streams live prices for: every open sandbox
position and pending order, any the user asked to watch (ADR 13 in
docs/adr), and any a page open in the web app shows (ADR 32)."""

from collections.abc import Callable, Iterable, Sequence

from openticker.ports.models import Exchange, Instrument
from openticker.storage.sqlite.instruments_repo import get_instrument
from openticker.storage.sqlite.sandbox_repo import list_pending_orders, list_positions


def watched_instruments(
    watch: Sequence[tuple[str, Exchange]],
    browser: Callable[[], Iterable[Instrument]] = tuple,
) -> list[Instrument]:
    """Symbols missing from the instrument master are skipped, not fatal: the
    feed keeps running for the rest until the next sync."""
    wanted = [(p.symbol, p.exchange) for p in list_positions() if p.position.quantity]
    wanted += [(o.symbol, o.exchange) for o in list_pending_orders()]
    wanted += [(symbol, exchange.value) for symbol, exchange in watch]
    found: dict[tuple[str, str], Instrument] = {}
    for symbol, exchange in wanted:
        if (symbol, exchange) not in found and (instrument := get_instrument(symbol, exchange)):
            found[(symbol, exchange)] = instrument
    for instrument in browser():
        found.setdefault((instrument.symbol, instrument.exchange), instrument)
    return list(found.values())
