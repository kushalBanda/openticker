"""Loads the charge rates: the file shipped with the package, or
`$OPENTICKER_HOME/charges.json` when present, which replaces it entirely
(ADR 28 in docs/adr)."""

import json
from importlib.resources import files

from openticker.core.orders.charges import ChargeBook, ChargeBookError, parse_charge_book
from openticker.storage.sqlite.engine import get_data_dir


def load_charge_book() -> ChargeBook:
    override = get_data_dir() / "charges.json"
    if override.exists():
        source, text = str(override), override.read_text()
    else:
        source, text = (
            "the shipped charges file",
            files("openticker").joinpath("data/charges.json").read_text(),
        )
    try:
        return parse_charge_book(json.loads(text))
    except (json.JSONDecodeError, ChargeBookError) as exc:
        raise ChargeBookError(f"{source}: {exc}") from exc
