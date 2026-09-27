"""Named lists of instruments to watch (ADR 36 in docs/adr). The web app and
agents share them: each change is published as `WatchlistChanged`, so the
audit log says who made it and the web app hears of it as it happens."""

from collections.abc import Sequence
from datetime import datetime

from openticker.events.bus import EventPublisher
from openticker.events.types import WatchlistChanged
from openticker.ports.models import Instrument
from openticker.storage.sqlite import watchlists_repo
from openticker.storage.sqlite.instruments_repo import get_instrument
from openticker.storage.sqlite.watchlists_repo import (
    DuplicateWatchlistNameError,
    Watchlist,
    WatchlistItem,
)
from openticker.use_cases.resolve_instrument import resolve_instrument

MAX_NAME = 40


class UnknownWatchlistError(LookupError):
    pass


class InvalidWatchlistNameError(ValueError):
    pass


def get_watchlists() -> list[Watchlist]:
    return watchlists_repo.list_watchlists()


def instruments_of(watchlist: Watchlist) -> list[Instrument | None]:
    """Each item's instrument from the master, in the list's order; None for
    one the master doesn't have (a new home that hasn't synced yet)."""
    return [get_instrument(item.symbol, item.exchange) for item in watchlist.items]


def create_watchlist(
    name: str, events: EventPublisher, now: datetime, triggered_by: str
) -> Watchlist:
    name = _valid_name(name)
    created = watchlists_repo.insert_watchlist(name, now)
    events.publish(_changed(created, "created", triggered_by, now))
    return created


def rename_watchlist(
    watchlist_id: str, name: str, events: EventPublisher, now: datetime, triggered_by: str
) -> Watchlist:
    name = _valid_name(name, keep=watchlist_id)
    before = _existing(watchlist_id)
    renamed = watchlists_repo.rename_watchlist(watchlist_id, name)
    if renamed is None:
        raise _unknown(watchlist_id)
    if renamed.name != before.name:
        events.publish(_changed(renamed, "renamed", triggered_by, now, previous_name=before.name))
    return renamed


def delete_watchlist(
    watchlist_id: str, events: EventPublisher, now: datetime, triggered_by: str
) -> Watchlist:
    """The list as it was."""
    gone = _existing(watchlist_id)
    if not watchlists_repo.delete_watchlist(watchlist_id):
        raise _unknown(watchlist_id)
    events.publish(_changed(gone, "deleted", triggered_by, now))
    return gone


def add_to_watchlist(
    watchlist_id: str,
    instruments: Sequence[tuple[str, str]],
    events: EventPublisher,
    now: datetime,
    triggered_by: str,
) -> Watchlist:
    """`instruments` are (symbol, exchange) pairs, each checked against the
    instrument master. One already on the list is left where it is."""
    wanted = [
        WatchlistItem(exchange=found.exchange.value, symbol=found.symbol)
        for found in (resolve_instrument(symbol, exchange) for symbol, exchange in instruments)
    ]
    outcome = watchlists_repo.add_items(watchlist_id, wanted)
    if outcome is None:
        raise _unknown(watchlist_id)
    watchlist, added = outcome
    if added:
        events.publish(
            _changed(watchlist, "added", triggered_by, now, tuple(i.symbol for i in added))
        )
    return watchlist


def remove_from_watchlist(
    watchlist_id: str,
    instruments: Sequence[tuple[str, str]],
    events: EventPublisher,
    now: datetime,
    triggered_by: str,
) -> Watchlist:
    """One not on the list is ignored; nothing is checked against the
    instrument master, so an expired contract can still be removed."""
    unwanted = [WatchlistItem(exchange=exchange, symbol=symbol) for symbol, exchange in instruments]
    outcome = watchlists_repo.remove_items(watchlist_id, unwanted)
    if outcome is None:
        raise _unknown(watchlist_id)
    watchlist, removed = outcome
    if removed:
        events.publish(
            _changed(watchlist, "removed", triggered_by, now, tuple(i.symbol for i in removed))
        )
    return watchlist


def _valid_name(name: str, keep: str | None = None) -> str:
    """Trimmed; unique whatever its case, so "Banks" and "banks" aren't two lists."""
    name = " ".join(name.split())
    if not name or len(name) > MAX_NAME:
        raise InvalidWatchlistNameError(f"a watchlist's name is 1 to {MAX_NAME} characters")
    for other in watchlists_repo.list_watchlists():
        if other.watchlist_id != keep and other.name.casefold() == name.casefold():
            raise DuplicateWatchlistNameError(f"a watchlist named {other.name!r} already exists")
    return name


def _existing(watchlist_id: str) -> Watchlist:
    found = watchlists_repo.get_watchlist(watchlist_id)
    if found is None:
        raise _unknown(watchlist_id)
    return found


def _unknown(watchlist_id: str) -> UnknownWatchlistError:
    return UnknownWatchlistError(
        f"no watchlist {watchlist_id!r}; list_watchlists shows each list's id"
    )


def _changed(
    watchlist: Watchlist,
    change: str,
    triggered_by: str,
    now: datetime,
    symbols: tuple[str, ...] = (),
    previous_name: str | None = None,
) -> WatchlistChanged:
    return WatchlistChanged(
        watchlist_id=watchlist.watchlist_id,
        name=watchlist.name,
        change=change,
        triggered_by=triggered_by,
        symbols=symbols,
        previous_name=previous_name,
        occurred_at=now,
    )
