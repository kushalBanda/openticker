"""The paper desk an eval's manager works: a NIFTY market whose prices the
seed moves, registered as `zerodha` so the skill's default broker is the
one it finds, and a clock that stands at each seeded moment, then runs at
real speed through the turn."""

import time
from dataclasses import replace
from datetime import datetime, timedelta, tzinfo

from openticker.adapters.brokers import registry
from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.sandbox.broker import SandboxBroker
from openticker.composition import build_event_bus, sandbox_settings
from openticker.core.strategies.models import OptionsStrategySpec
from openticker.events import types as event_types
from openticker.events.bus import EventBus
from openticker.ports.models import Credentials, Exchange, Instrument, Quote, Tick
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite.credentials_repo import save_credentials
from openticker.storage.sqlite.instruments_repo import get_instrument
from openticker.use_cases.strategies.control import request_start, schedule_strategy
from openticker.use_cases.strategies.define import create_strategy
from openticker.use_cases.strategies.runner import RunnerContext, process_commands, step_runs
from tests.fixtures.events import SET_UP_AT, Recorded
from tests.fixtures.fake_broker import FAKE_LAST_PRICE
from tests.fixtures.priced_broker import PricedBroker
from tests.fixtures.strategies import list_nifty_market

BROKER = "zerodha"
CE = "NIFTY22SEP262500CE"
PE = "NIFTY22SEP262500PE"


class EvalClock:
    """Stands at `at` while the desk is seeded; from `run()` on, real time
    passes from there, so the turn's calls and audit entries keep order."""

    def __init__(self, at: datetime) -> None:
        self._at = at
        self._since: float | None = None

    def set(self, at: datetime) -> None:
        self._at, self._since = at, None

    def run(self) -> None:
        self._since = time.monotonic()

    def __call__(self) -> datetime:
        if self._since is None:
            return self._at
        return self._at + timedelta(seconds=time.monotonic() - self._since)


class _Market(PricedBroker):
    """Quotes stamped with the eval's clock, not the wall's."""

    def __init__(self, clock: EvalClock) -> None:
        super().__init__(FAKE_LAST_PRICE)
        self._clock = clock

    def get_quote(self, instrument: Instrument) -> Quote:
        return replace(super().get_quote(instrument), as_of=self._clock())


class EvalDesk:
    def __init__(self, clock: EvalClock) -> None:
        self.clock = clock
        _stamp_events_with(clock)
        list_nifty_market()
        self.market = _Market(clock)
        self.market.prices = {CE: 100.0, PE: 100.0}
        registry.register(BROKER, lambda: self.market)
        save_credentials(Credentials(BROKER, "eval", None, clock() + timedelta(days=1)))
        self.events: EventBus = build_event_bus({})  # audited, never notified
        self.sandbox = SandboxBroker(BROKER, self.market, sandbox_settings({}), clock)
        self.prices = LatestPrices()
        self.runner = RunnerContext(
            sandbox=lambda broker: self.sandbox,
            latest=self.prices.get,
            events=self.events,
            calendar=load_calendar(),
            capital_cap=None,
        )

    def start(self, name: str, spec: OptionsStrategySpec) -> str:
        stored = create_strategy(name, spec, self.clock())
        request_start(stored.id, BROKER, "ui", self.clock())
        self.step()
        return stored.id

    def schedule(self, name: str, spec: OptionsStrategySpec) -> str:
        stored = create_strategy(name, spec, self.clock())
        schedule_strategy(stored.id, BROKER, Recorded(), "you", SET_UP_AT)
        return stored.id

    def move(self, ce: float, pe: float) -> None:
        """Both legs' prices, streamed and filled at; the runs' rules act on them."""
        for symbol, price in {CE: ce, PE: pe}.items():
            self.market.prices[symbol] = price
            instrument = get_instrument(symbol, Exchange.NFO.value)
            assert instrument is not None
            self.prices.update([Tick(instrument, price, self.clock())])
        step_runs(self.runner, self.clock())

    def step(self) -> None:
        """Carries out the starts and stops asked for, as the daemon does.
        Runs aren't watched here: the prices don't move during the turn."""
        process_commands(self.runner, self.clock())


def _stamp_events_with(clock: EvalClock) -> None:
    """Events stamped with the eval's clock, so the audit log reads as the day."""

    class _EvalTime:  # what event types read the time from
        @staticmethod
        def now(tz: tzinfo) -> datetime:
            return clock().astimezone(tz)

    event_types.datetime = _EvalTime  # type: ignore[attr-defined,assignment]
