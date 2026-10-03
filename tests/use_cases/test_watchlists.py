from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from openticker.events.types import WatchlistChanged
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.storage.sqlite.models import InstrumentRow
from openticker.storage.sqlite.watchlists_repo import (
    MAX_ITEMS,
    MAX_WATCHLISTS,
    DuplicateWatchlistNameError,
    WatchlistItem,
    WatchlistLimitError,
)
from openticker.use_cases.resolve_instrument import UnknownInstrumentError
from openticker.use_cases.watchlists import (
    InvalidWatchlistNameError,
    UnknownWatchlistError,
    add_to_watchlist,
    create_watchlist,
    delete_watchlist,
    get_watchlists,
    instruments_of,
    remove_from_watchlist,
    rename_watchlist,
)
from tests.fixtures.fake_broker import FAKE_INSTRUMENT

NOW = datetime(2026, 9, 28, 5, 0, tzinfo=UTC)
TCS = replace(FAKE_INSTRUMENT, symbol="TCS", broker_symbol="TCS", token="fake-2")
INFY = replace(FAKE_INSTRUMENT, symbol="INFY", broker_symbol="INFY", token="fake-3")


class _Events:
    def __init__(self) -> None:
        self.events: list[WatchlistChanged] = []

    def publish(self, event: object) -> None:
        assert isinstance(event, WatchlistChanged)
        self.events.append(event)


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT, TCS, INFY])


def _symbols(watchlist_id: str) -> list[str]:
    [found] = [w for w in get_watchlists() if w.watchlist_id == watchlist_id]
    return [item.symbol for item in found.items]


def test_create_add_remove_round_trip() -> None:
    events = _Events()
    core = create_watchlist("  Core  ", events, NOW, "ui")
    assert core.name == "Core" and core.items == ()

    add_to_watchlist(
        core.watchlist_id, [("TCS", "NSE"), ("RELIANCE", "NSE")], events, NOW, "mcp:claude-code"
    )
    # Already there stays where it is; new ones go to the end.
    after = add_to_watchlist(
        core.watchlist_id, [("RELIANCE", "NSE"), ("INFY", "NSE")], events, NOW, "ui"
    )
    assert [i.symbol for i in after.items] == ["TCS", "RELIANCE", "INFY"]
    assert [i.symbol if i else None for i in instruments_of(after)] == ["TCS", "RELIANCE", "INFY"]

    remove_from_watchlist(
        core.watchlist_id, [("TCS", "NSE"), ("NOTHERE", "NSE")], events, NOW, "ui"
    )
    assert _symbols(core.watchlist_id) == ["RELIANCE", "INFY"]


def test_lists_keep_the_order_they_were_made() -> None:
    events = _Events()
    for name in ("Core", "Banks", "F&O ideas"):
        create_watchlist(name, events, NOW, "ui")
    assert [w.name for w in get_watchlists()] == ["Core", "Banks", "F&O ideas"]


def test_duplicate_name_refused_whatever_its_case() -> None:
    events = _Events()
    banks = create_watchlist("Banks", events, NOW, "ui")
    with pytest.raises(DuplicateWatchlistNameError, match="Banks"):
        create_watchlist("banks", events, NOW, "ui")
    other = create_watchlist("Core", events, NOW, "ui")
    with pytest.raises(DuplicateWatchlistNameError):
        rename_watchlist(other.watchlist_id, "BANKS", events, NOW, "ui")
    # A list may change its own name's case.
    assert rename_watchlist(banks.watchlist_id, "BANKS", events, NOW, "ui").name == "BANKS"


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_blank_or_long_name_refused(name: str) -> None:
    with pytest.raises(InvalidWatchlistNameError):
        create_watchlist(name, _Events(), NOW, "ui")


def test_unknown_instrument_refused_and_nothing_added() -> None:
    events = _Events()
    core = create_watchlist("Core", events, NOW, "ui")
    with pytest.raises(UnknownInstrumentError, match="NOPE"):
        add_to_watchlist(core.watchlist_id, [("TCS", "NSE"), ("NOPE", "NSE")], events, NOW, "ui")
    assert _symbols(core.watchlist_id) == []


def test_unknown_watchlist_refused() -> None:
    events = _Events()
    with pytest.raises(UnknownWatchlistError, match="list_watchlists"):
        add_to_watchlist("wl_nope", [("TCS", "NSE")], events, NOW, "ui")
    with pytest.raises(UnknownWatchlistError):
        rename_watchlist("wl_nope", "X", events, NOW, "ui")
    with pytest.raises(UnknownWatchlistError):
        delete_watchlist("wl_nope", events, NOW, "ui")
    with pytest.raises(UnknownWatchlistError):
        remove_from_watchlist("wl_nope", [("TCS", "NSE")], events, NOW, "ui")


def test_fifty_item_cap() -> None:
    names = [f"S{n}" for n in range(MAX_ITEMS + 1)]
    upsert_instruments(
        [replace(FAKE_INSTRUMENT, symbol=n, broker_symbol=n, token=n) for n in names]
    )
    events = _Events()
    core = create_watchlist("Core", events, NOW, "ui")
    add_to_watchlist(core.watchlist_id, [(n, "NSE") for n in names[:-1]], events, NOW, "ui")

    with pytest.raises(WatchlistLimitError, match="50"):
        add_to_watchlist(core.watchlist_id, [(names[-1], "NSE")], events, NOW, "ui")
    # Adding what is already on a full list is fine.
    add_to_watchlist(core.watchlist_id, [(names[0], "NSE")], events, NOW, "ui")
    assert len(_symbols(core.watchlist_id)) == MAX_ITEMS


def test_twenty_list_cap() -> None:
    events = _Events()
    for n in range(MAX_WATCHLISTS):
        create_watchlist(f"List {n}", events, NOW, "ui")
    with pytest.raises(WatchlistLimitError, match="delete one"):
        create_watchlist("One more", events, NOW, "ui")


def test_delete_removes_its_items_too() -> None:
    events = _Events()
    core = create_watchlist("Core", events, NOW, "ui")
    add_to_watchlist(core.watchlist_id, [("TCS", "NSE")], events, NOW, "ui")
    gone = delete_watchlist(core.watchlist_id, events, NOW, "ui")

    assert gone.items == (WatchlistItem(exchange="NSE", symbol="TCS"),)
    assert get_watchlists() == []
    again = create_watchlist("Core", events, NOW, "ui")
    assert again.items == ()


def test_an_instrument_gone_from_the_master_stays_until_removed() -> None:
    events = _Events()
    core = create_watchlist("Core", events, NOW, "ui")
    add_to_watchlist(core.watchlist_id, [("TCS", "NSE")], events, NOW, "ui")
    with Session(get_engine()) as session:  # a fresh master without it
        session.execute(delete(InstrumentRow).where(InstrumentRow.symbol == "TCS"))
        session.commit()

    [listed] = get_watchlists()
    assert instruments_of(listed) == [None]
    removed = remove_from_watchlist(core.watchlist_id, [("TCS", "NSE")], events, NOW, "ui")
    assert removed.items == ()


def test_each_change_publishes_watchlist_changed() -> None:
    events = _Events()
    core = create_watchlist("Core", events, NOW, "ui")
    add_to_watchlist(
        core.watchlist_id, [("TCS", "NSE"), ("INFY", "NSE")], events, NOW, "mcp:claude-code"
    )
    add_to_watchlist(core.watchlist_id, [("TCS", "NSE")], events, NOW, "ui")  # no change
    remove_from_watchlist(core.watchlist_id, [("INFY", "NSE")], events, NOW, "ui")
    remove_from_watchlist(core.watchlist_id, [("INFY", "NSE")], events, NOW, "ui")  # no change
    rename_watchlist(core.watchlist_id, "Main", events, NOW, "ui")
    rename_watchlist(core.watchlist_id, "Main", events, NOW, "ui")  # no change
    delete_watchlist(core.watchlist_id, events, NOW, "ui")

    said = [(e.change, e.name, e.symbols, e.previous_name, e.triggered_by) for e in events.events]
    assert said == [
        ("created", "Core", (), None, "ui"),
        ("added", "Core", ("TCS", "INFY"), None, "mcp:claude-code"),
        ("removed", "Core", ("INFY",), None, "ui"),
        ("renamed", "Main", (), "Core", "ui"),
        ("deleted", "Main", (), None, "ui"),
    ]
    assert {e.watchlist_id for e in events.events} == {core.watchlist_id}
    assert all(e.occurred_at == NOW for e in events.events)
