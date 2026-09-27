from datetime import UTC, datetime, time

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.core.pnl import IntradayPoint
from openticker.core.strategies.runs import Run, RunStatus
from openticker.events.subscribers.audit_log import record_event
from openticker.events.types import OrderPlaced, PaperAccountReset
from openticker.ports.models import Product, Side
from openticker.storage.sqlite import pnl_repo, runs_repo, scripts_repo
from openticker.storage.sqlite.audit_repo import list_audit
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.storage.sqlite.strategies_repo import (
    find_strategy,
    insert_strategy,
    write_transaction,
)
from openticker.use_cases.reset_paper_account import (
    ResetConfirmationError,
    ResetRefusedError,
    reset_paper_account,
)
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker
from tests.fixtures.strategies import STRADDLE

OPEN = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST
CAPITAL = 500_000.0


class _Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _sandbox() -> SandboxBroker:
    return SandboxBroker(
        "fake", PricedBroker(1000.0), SandboxSettings(starting_capital=CAPITAL), lambda: OPEN
    )


def _trade(sandbox: SandboxBroker) -> None:
    """A round trip, an open position and a resting order."""
    for side, qty in ((Side.BUY, 10), (Side.SELL, 4)):
        request = OrderRequest(
            FAKE_INSTRUMENT, side, qty, Product.MIS, OrderType.MARKET, None, "ui"
        )
        assert sandbox.place_order(request).status is OrderStatus.FILLED
    resting = OrderRequest(FAKE_INSTRUMENT, Side.BUY, 1, Product.MIS, OrderType.LIMIT, 900.0, "ui")
    assert sandbox.place_order(resting).status is OrderStatus.PENDING


def _running_strategy() -> None:
    stored = insert_strategy("Short straddle", STRADDLE, OPEN)
    run = Run(
        id=runs_repo.new_run_id(),
        strategy_id=stored.id,
        broker="fake",
        product=Product.MIS,
        status=RunStatus.OPEN,
        trigger="ui",
        started_at=OPEN,
        legs=(),
    )
    with write_transaction() as session:
        runs_repo.insert_run(session, run)


def test_refused_without_the_exact_confirmation() -> None:
    sandbox = _sandbox()
    _trade(sandbox)

    with pytest.raises(ResetConfirmationError, match="type RESET"):
        reset_paper_account("reset", CAPITAL, _Recorder(), OPEN, "ui")

    assert sandbox.get_positions()


def test_refused_while_a_strategy_runs_and_names_it() -> None:
    sandbox = _sandbox()
    _trade(sandbox)
    _running_strategy()

    with pytest.raises(ResetRefusedError, match="Stop strategy Short straddle first"):
        reset_paper_account("RESET", CAPITAL, _Recorder(), OPEN, "ui")

    assert sandbox.get_positions()


def test_refused_while_a_script_runs() -> None:
    with write_transaction() as session:
        script = scripts_repo.insert_script(session, "rel_trail", "0" * 64, 10, OPEN)
        scripts_repo.add_run(session, script.id, "ui", OPEN)

    with pytest.raises(ResetRefusedError, match="script rel_trail"):
        reset_paper_account("RESET", CAPITAL, _Recorder(), OPEN, "ui")


def test_wipes_orders_trades_positions_and_restores_capital() -> None:
    sandbox = _sandbox()
    _trade(sandbox)
    events = _Recorder()

    pnl_repo.upsert_point(OPEN.date(), IntradayPoint(time(10, 30), 5.0, 0.0, 0.0, 5.0))
    reset = reset_paper_account("RESET", CAPITAL, events, OPEN, "ui")

    assert (reset.orders, reset.trades, reset.positions) == (3, 2, 1)
    assert sandbox.get_positions() == []
    assert sandbox.get_orderbook(50) == []
    funds = sandbox.get_funds()
    assert (funds.available_cash, funds.used_margin) == (CAPITAL, 0.0)
    assert events.events == [reset]
    assert pnl_repo.points_on(OPEN.date()) == []
    assert isinstance(reset, PaperAccountReset) and reset.triggered_by == "ui"


def test_keeps_the_audit_log_and_strategies() -> None:
    _trade(_sandbox())
    stored = insert_strategy("Short straddle", STRADDLE, OPEN)
    record_event(OrderPlaced("o1", "RELIANCE", "BUY", 10, "ui"))

    reset_paper_account("RESET", CAPITAL, _Recorder(), OPEN, "ui")

    assert [entry.event_type for entry in list_audit(10)] == ["OrderPlaced"]
    assert find_strategy(stored.id) is not None
