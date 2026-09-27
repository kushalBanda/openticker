"""Watchlists and the instruments on them (ADR 36 in docs/adr)."""

import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import WatchlistItemRow, WatchlistRow

MAX_WATCHLISTS = 20
MAX_ITEMS = 50  # per list: one quotes call covers it


class DuplicateWatchlistNameError(Exception):
    pass


class WatchlistLimitError(Exception):
    """Too many lists, or too many instruments on one."""


@dataclass(frozen=True)
class WatchlistItem:
    exchange: str
    symbol: str


@dataclass(frozen=True)
class Watchlist:
    watchlist_id: str
    name: str
    position: int
    created_at: datetime  # tz-aware UTC
    items: tuple[WatchlistItem, ...]  # in the order they were added


def list_watchlists() -> list[Watchlist]:
    """Every list, in the order they were made."""
    with Session(get_engine()) as session:
        rows = session.scalars(select(WatchlistRow).order_by(WatchlistRow.position)).all()
        return [_watchlist(session, row) for row in rows]


def get_watchlist(watchlist_id: str) -> Watchlist | None:
    with Session(get_engine()) as session:
        row = session.get(WatchlistRow, watchlist_id)
        return _watchlist(session, row) if row else None


def insert_watchlist(name: str, now: datetime) -> Watchlist:
    with Session(get_engine()) as session:
        if (session.scalar(select(func.count()).select_from(WatchlistRow)) or 0) >= MAX_WATCHLISTS:
            raise WatchlistLimitError(
                f"there are already {MAX_WATCHLISTS} watchlists; delete one first"
            )
        last = session.scalar(select(func.max(WatchlistRow.position)))
        row = WatchlistRow(
            id="wl_" + secrets.token_hex(6),
            name=name,
            position=(last or 0) + 1,
            created_at=now.astimezone(UTC).replace(tzinfo=None),
        )
        session.add(row)
        _commit(session, name)
        return _watchlist(session, row)


def rename_watchlist(watchlist_id: str, name: str) -> Watchlist | None:
    with Session(get_engine()) as session:
        row = session.get(WatchlistRow, watchlist_id)
        if row is None:
            return None
        row.name = name
        _commit(session, name)
        return _watchlist(session, row)


def delete_watchlist(watchlist_id: str) -> bool:
    """False when there is no such list."""
    with Session(get_engine()) as session:
        row = session.get(WatchlistRow, watchlist_id)
        if row is None:
            return False
        session.execute(delete(WatchlistItemRow).where(WatchlistItemRow.watchlist_id == row.id))
        session.delete(row)
        session.commit()
        return True


def add_items(
    watchlist_id: str, items: Sequence[WatchlistItem]
) -> tuple[Watchlist, list[WatchlistItem]] | None:
    """The list after adding, and what was new on it; None when there is no
    such list. Instruments already on it stay where they are."""
    with Session(get_engine()) as session:
        row = session.get(WatchlistRow, watchlist_id)
        if row is None:
            return None
        held = {(i.exchange, i.symbol) for i in _items(session, watchlist_id)}
        added: list[WatchlistItem] = []
        for item in items:
            if (item.exchange, item.symbol) not in held:
                held.add((item.exchange, item.symbol))
                added.append(item)
        if len(held) > MAX_ITEMS:
            raise WatchlistLimitError(
                f"{row.name} can hold {MAX_ITEMS} instruments; it has "
                f"{len(held) - len(added)}, and {len(added)} more don't fit"
            )
        last = session.scalar(
            select(func.max(WatchlistItemRow.position)).where(
                WatchlistItemRow.watchlist_id == watchlist_id
            )
        )
        for offset, item in enumerate(added, start=(last or 0) + 1):
            session.add(
                WatchlistItemRow(
                    watchlist_id=watchlist_id,
                    exchange=item.exchange,
                    symbol=item.symbol,
                    position=offset,
                )
            )
        session.commit()
        return _watchlist(session, row), added


def remove_items(
    watchlist_id: str, items: Sequence[WatchlistItem]
) -> tuple[Watchlist, list[WatchlistItem]] | None:
    """The list after removing, and what was on it and went; None when there
    is no such list."""
    with Session(get_engine()) as session:
        row = session.get(WatchlistRow, watchlist_id)
        if row is None:
            return None
        held = set(_items(session, watchlist_id))
        removed = [item for item in dict.fromkeys(items) if item in held]
        for item in removed:
            session.execute(
                delete(WatchlistItemRow).where(
                    WatchlistItemRow.watchlist_id == watchlist_id,
                    WatchlistItemRow.exchange == item.exchange,
                    WatchlistItemRow.symbol == item.symbol,
                )
            )
        session.commit()
        return _watchlist(session, row), removed


def _commit(session: Session, name: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        raise DuplicateWatchlistNameError(f"a watchlist named {name!r} already exists") from exc


def _items(session: Session, watchlist_id: str) -> tuple[WatchlistItem, ...]:
    rows = session.scalars(
        select(WatchlistItemRow)
        .where(WatchlistItemRow.watchlist_id == watchlist_id)
        .order_by(WatchlistItemRow.position)
    ).all()
    return tuple(WatchlistItem(exchange=r.exchange, symbol=r.symbol) for r in rows)


def _watchlist(session: Session, row: WatchlistRow) -> Watchlist:
    return Watchlist(
        watchlist_id=row.id,
        name=row.name,
        position=row.position,
        created_at=row.created_at.replace(tzinfo=UTC),
        items=_items(session, row.id),
    )
