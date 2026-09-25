"""Sandbox settings for tests whose subject isn't costs: market orders fill at
the last price and nothing is charged. Fills against the book and charges
(ADR 28 in docs/adr) are tested on their own, in tests/adapters/sandbox/test_costs.py."""

from dataclasses import replace

from openticker.adapters.sandbox.broker import SandboxSettings
from openticker.core.orders.charges import ChargeBook
from openticker.core.orders.fills import FillSettings

FRICTIONLESS = SandboxSettings(fills=FillSettings(slippage_ticks=0), charges=ChargeBook({}))


def frictionless(starting_capital: float = FRICTIONLESS.starting_capital) -> SandboxSettings:
    return replace(FRICTIONLESS, starting_capital=starting_capital)
