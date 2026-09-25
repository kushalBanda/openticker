import json
from pathlib import Path

import pytest

from openticker.core.orders.charges import ChargeBookError, Segment
from openticker.ports.models import Exchange
from openticker.storage.charges_file import load_charge_book
from openticker.storage.sqlite.engine import get_data_dir


def test_the_shipped_book_loads() -> None:
    assert (Segment.OPTIONS, Exchange.NFO) in load_charge_book().schedules


def test_an_override_replaces_the_shipped_book() -> None:
    override = {
        "source": "my broker",
        "as_of": "2026-10-01",
        "gst_rate": 0.18,
        "schedules": [
            {
                "segment": "options",
                "exchange": "NFO",
                "charges": [{"key": "brokerage", "basis": "order", "flat": 10}],
            }
        ],
    }
    _write(override)

    book = load_charge_book()

    assert list(book.schedules) == [(Segment.OPTIONS, Exchange.NFO)]
    assert book.schedules[(Segment.OPTIONS, Exchange.NFO)].source == "my broker"


def test_a_broken_override_says_which_file() -> None:
    path = _write({"source": "x"})

    with pytest.raises(ChargeBookError, match=str(path)):
        load_charge_book()


def _write(data: object) -> Path:
    path = get_data_dir() / "charges.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path
