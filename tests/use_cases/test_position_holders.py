from dataclasses import replace

from openticker.core.orders.models import OrderStatus, OrderType
from openticker.core.pnl import Source
from openticker.core.strategies.runs import LegStatus, Run, RunLeg, RunStatus
from openticker.ports.models import Exchange, Instrument, InstrumentType, Position, Product, Side
from openticker.storage.sqlite import runs_repo, sandbox_repo
from openticker.storage.sqlite.sandbox_repo import StoredOrder
from openticker.storage.sqlite.strategies_repo import insert_strategy, write_transaction
from openticker.use_cases.position_holders import Holder, Holding, holders
from tests.fixtures.strategies import NOW, STRADDLE

FUT = Instrument(
    symbol="NIFTY27OCT26FUT",
    broker_symbol="NIFTY26OCTFUT",
    exchange=Exchange.NFO,
    broker_exchange="NFO",
    token="1",
    expiry=None,
    strike=None,
    lot_size=75,
    instrument_type=InstrumentType.FUT,
    tick_size=0.05,
)
KEY = ("NFO", FUT.symbol, Product.NRML)


def _position(quantity: int, instrument: Instrument = FUT) -> Position:
    return Position(instrument, Product.NRML, quantity, 24858.2, 24889.4, 0.0, None)


def _strategy(name: str) -> str:
    return insert_strategy(name, STRADDLE, NOW).id


def _run(strategy_id: str, *legs: tuple[str, Side, int]) -> None:
    run = Run(
        id=runs_repo.new_run_id(),
        strategy_id=strategy_id,
        broker="zerodha",
        product=Product.NRML,
        status=RunStatus.OPEN,
        trigger="mcp",
        started_at=NOW,
        legs=tuple(
            RunLeg(leg_id, FUT.symbol, Exchange.NFO, side, quantity, LegStatus.OPEN, 24850.0, NOW)
            for leg_id, side, quantity in legs
        ),
    )
    with write_transaction() as session:
        runs_repo.insert_run(session, run)


def _filled(side: Side, triggered_by: str, strategy_id: str | None = None) -> None:
    order = StoredOrder(
        order_id=f"SB{triggered_by}{side}",
        placed_at=NOW,
        exchange="NFO",
        symbol=FUT.symbol,
        side=side,
        quantity=75,
        product=Product.NRML,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        fill_price=24850.0,
        reason=None,
        triggered_by=triggered_by,
        strategy_id=strategy_id,
        run_id=None,
    )
    with sandbox_repo.fill_transaction() as session:
        sandbox_repo.record_order(session, order)


def test_position_fully_held_by_strategy() -> None:
    trend = _strategy("NIFTY futures trend")
    _run(trend, ("leg1", Side.BUY, 150))

    assert holders([_position(150)]) == {
        KEY: Holding(
            (Holder(trend, "NIFTY futures trend", Source.STRATEGY, 150, ("leg1",)),), False
        )
    }


def test_shared_position_splits_strategy_and_you() -> None:
    trend = _strategy("NIFTY futures trend")
    _run(trend, ("leg1", Side.BUY, 75))
    _filled(Side.BUY, "strategy:" + trend, trend)
    _filled(Side.BUY, "ui")

    assert holders([_position(150)])[KEY] == Holding(
        (
            Holder(trend, "NIFTY futures trend", Source.STRATEGY, 75, ("leg1",)),
            Holder(None, None, Source.YOU, 75),
        ),
        False,
    )


def test_rest_is_labelled_by_who_added_to_it_last() -> None:
    _filled(Side.BUY, "ui")
    _filled(Side.BUY, "mcp:claude-code")
    _filled(Side.SELL, "mcp:codex")  # took some off; didn't add

    (rest,) = holders([_position(75)])[KEY].holders
    assert rest.source is Source.CLAUDE_CODE


def test_two_strategies_on_one_contract_counted_separately() -> None:
    a, b = _strategy("A"), _strategy("B")
    _run(a, ("a1", Side.SELL, 75))
    _run(b, ("b1", Side.SELL, 75), ("b2", Side.SELL, 75))

    holding = holders([_position(-225)])[KEY]
    assert [(h.strategy_id, h.quantity, h.leg_ids) for h in holding.holders] == [
        (a, -75, ("a1",)),
        (b, -150, ("b1", "b2")),
    ]
    assert not holding.shared


def test_legs_exceeding_position_marked_shared() -> None:
    a, b = _strategy("A"), _strategy("B")
    _run(a, ("a1", Side.BUY, 75))
    _run(b, ("b1", Side.SELL, 150))

    holding = holders([_position(-75)])[KEY]
    assert holding.shared
    assert [h.strategy_id for h in holding.holders] == [a, b]  # no rest when they don't fit


def test_no_active_runs_all_you() -> None:
    trend = _strategy("NIFTY futures trend")
    _run(trend, ("leg1", Side.BUY, 75))
    ended = replace(runs_repo.active_runs()[0], status=RunStatus.ENDED)
    runs_repo.save_run(ended)
    _filled(Side.BUY, "ui")

    assert holders([_position(75), _position(0, replace(FUT, symbol="OTHER"))]) == {
        KEY: Holding((Holder(None, None, Source.YOU, 75),), False)
    }
