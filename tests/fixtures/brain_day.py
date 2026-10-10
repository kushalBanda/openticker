"""A trading day for the brain's day record and debriefs: a strategy run
that opened and closed on Monday, a round trip placed by hand that day, and
a fill on Tuesday that Monday's record must leave out."""

from dataclasses import dataclass, replace
from datetime import datetime

from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.core.risk.models import StrategyStopReason
from openticker.core.strategies.runs import Run, RunStatus
from openticker.ports.models import Product, Side
from openticker.storage.sqlite import runs_repo
from openticker.storage.sqlite.strategies_repo import insert_strategy, write_transaction
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.pnl_desk import MONDAY, TUESDAY, Desk, at, new_desk
from tests.fixtures.strategies import STRADDLE


@dataclass(frozen=True)
class Day:
    desk: Desk
    strategy_id: str
    run_id: str
    manual_orders: tuple[str, str]  # Monday's buy, then its sell
    tuesday_order: str


def place(desk: Desk, side: Side, qty: int, who: str, run: Run | None = None) -> str:
    request = OrderRequest(
        FAKE_INSTRUMENT,
        side,
        qty,
        Product.MIS,
        OrderType.MARKET,
        None,
        who,
        run.strategy_id if run else None,
        run.id if run else None,
    )
    result = desk.sandbox.place_order(request)
    assert result.status is OrderStatus.FILLED and result.broker_order_id
    return result.broker_order_id


def monday() -> Day:
    desk = new_desk()
    desk.now = at(MONDAY, 9, 30)
    strategy = insert_strategy("Straddle", STRADDLE, desk.now)
    run = Run(
        id=runs_repo.new_run_id(),
        strategy_id=strategy.id,
        broker="fake",
        product=Product.MIS,
        status=RunStatus.OPEN,
        trigger="schedule",
        started_at=desk.now,
        legs=(),
    )
    with write_transaction() as session:
        runs_repo.insert_run(session, run)
    place(desk, Side.SELL, 10, f"strategy:{strategy.id}", run)

    desk.now = at(MONDAY, 10, 55)
    desk.market.price = 990.0
    place(desk, Side.BUY, 10, f"strategy:{strategy.id}", run)
    end(run, at(MONDAY, 11, 0))

    desk.now = at(MONDAY, 11, 30)
    bought = place(desk, Side.BUY, 5, "ui")

    desk.now = at(MONDAY, 14, 0)
    desk.market.price = 1010.0
    sold = place(desk, Side.SELL, 5, "mcp:claude-code")

    desk.now = at(TUESDAY, 10, 0)
    tuesday = place(desk, Side.BUY, 1, "ui")
    desk.now = at(TUESDAY, 15, 0)
    return Day(desk, strategy.id, run.id, (bought, sold), tuesday)


def end(run: Run, ended_at: datetime) -> None:
    stored = runs_repo.find_run(run.id)
    assert stored is not None
    runs_repo.save_run(
        replace(
            stored, status=RunStatus.ENDED, ended_at=ended_at, stop_reason=StrategyStopReason.KILL
        )
    )
