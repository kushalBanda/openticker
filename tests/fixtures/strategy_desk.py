"""A sandbox over a NIFTY market whose prices a test moves, and the strategy
runner's view of it."""

from datetime import timedelta

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
from openticker.core.strategies.models import OptionsStrategySpec
from openticker.core.strategies.runs import Run
from openticker.ports.models import Exchange, Tick
from openticker.storage.sqlite import runs_repo
from openticker.storage.sqlite.instruments_repo import get_instrument
from openticker.use_cases.strategies.control import request_start
from openticker.use_cases.strategies.define import create_strategy
from openticker.use_cases.strategies.runner import RunnerContext, process_commands, step_runs
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.fake_broker import FAKE_LAST_PRICE
from tests.fixtures.priced_broker import PricedBroker
from tests.fixtures.strategies import NOW, STRADDLE, list_nifty_market

CE = "NIFTY22SEP262500CE"
PE = "NIFTY22SEP262500PE"
LOT = 65


class _Events:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)

    def of(self, kind: type) -> list[object]:
        return [event for event in self.events if isinstance(event, kind)]


class Desk:
    def __init__(self) -> None:
        list_nifty_market()
        self.now = NOW
        self.market = PricedBroker(FAKE_LAST_PRICE)
        self.market.prices = {CE: 100.0, PE: 100.0}
        self.sandbox = SandboxBroker("fake", self.market, SandboxSettings(), lambda: self.now)
        self.prices = LatestPrices()
        self.events = _Events()
        self.context = RunnerContext(
            sandbox=lambda broker: self.sandbox,
            latest=self.prices.get,
            events=self.events,
            calendar=NO_HOLIDAYS,
            capital_cap=None,
        )

    def start(self, spec: OptionsStrategySpec = STRADDLE, name: str = "straddle") -> str:
        stored = create_strategy(name, spec, self.now)
        request_start(stored.id, "fake", "mcp", self.now)
        process_commands(self.context, self.now)
        return stored.id

    def tick(self, seconds: int = 1, **prices: float) -> None:
        """Moves time on, then prices: both the stream and what an order fills at."""
        self.now += timedelta(seconds=seconds)
        for symbol, price in {CE: prices.get("ce"), PE: prices.get("pe")}.items():
            if price is None:
                continue
            self.market.prices[symbol] = price
            instrument = get_instrument(symbol, Exchange.NFO.value)
            assert instrument is not None
            self.prices.update([Tick(instrument, price, self.now)])
        step_runs(self.context, self.now)

    def run(self, strategy_id: str) -> Run:
        runs = runs_repo.list_runs(strategy_id, 1)
        assert runs
        return runs[0]

    def held(self) -> dict[str, int]:
        return {p.instrument.symbol: p.quantity for p in self.sandbox.open_positions()}
