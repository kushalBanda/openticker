"""MCP tools end to end — tool -> registry -> use case -> port -> storage ->
response — with `FakeBrokerPort` registered under its own name, so nothing
touches Kite."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import Tool

from openticker.adapters.brokers import registry
from openticker.adapters.inbound import mcp_server
from openticker.ports.models import Exchange, InstrumentType, Interval, Product, Side
from tests.fixtures.fake_broker import FAKE_LAST_PRICE, FakeBrokerPort

TRADING_TIME = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST


@pytest.fixture(autouse=True)
def _market_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "clock", lambda: TRADING_TIME)


@pytest.fixture(autouse=True)
def _fake_broker_registered() -> Iterator[None]:
    registry.register("fake", FakeBrokerPort)
    yield
    del registry.BROKER_REGISTRY["fake"]


def _tools() -> list[Tool]:
    return asyncio.run(mcp_server.mcp.list_tools())


def test_get_quote_after_sync_returns_resolved_quote() -> None:
    assert mcp_server.sync_instruments(broker="fake").instrument_count == 1

    result = mcp_server.get_quote(broker="fake", symbol="RELIANCE", exchange=Exchange.NSE)

    assert result.symbol == "RELIANCE"
    assert result.last_price == FAKE_LAST_PRICE
    assert result.as_of.utcoffset() is not None


def test_get_historical_bars_returns_exchange_local_times_and_explains_truncation() -> None:
    mcp_server.sync_instruments(broker="fake")

    result = mcp_server.get_historical_bars(
        broker="fake",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        interval=Interval.DAY,
        start_date=date(2026, 9, 18),
        end_date=date(2026, 9, 19),
        max_bars=1,
    )

    assert result.total_bars == 2
    assert [bar.timestamp.isoformat() for bar in result.bars] == ["2026-09-19T00:00:00+05:30"]
    assert result.note is not None and "max_bars" in result.note


def test_search_instruments_finds_synced_symbol() -> None:
    mcp_server.sync_instruments(broker="fake")

    result = mcp_server.search_instruments(query="relian", instrument_type=InstrumentType.EQ)

    assert [instrument.symbol for instrument in result.instruments] == ["RELIANCE"]
    assert result.truncated is False


def test_agent_fixable_errors_reach_the_agent_with_their_message() -> None:
    with pytest.raises(ToolError, match="sync_instruments"):
        mcp_server.get_quote(broker="fake", symbol="RELIANCE", exchange=Exchange.NSE)

    with pytest.raises(ToolError, match="no broker adapter registered"):
        mcp_server.get_quote(broker="nonexistent", symbol="RELIANCE", exchange=Exchange.NSE)


def test_every_tool_is_fully_described_for_agents() -> None:
    """Conventions from ADR 8 in docs/adr, enforced for every tool, current and future."""
    for tool in _tools():
        assert tool.title, tool.name
        assert tool.description, tool.name
        assert tool.annotations is not None, tool.name
        assert tool.annotations.read_only_hint is not None, tool.name
        assert tool.annotations.open_world_hint is not None, tool.name
        if not tool.annotations.read_only_hint:
            assert tool.annotations.destructive_hint is not None, tool.name
            assert tool.annotations.idempotent_hint is not None, tool.name
        assert tool.output_schema is not None, tool.name
        for name, schema in tool.input_schema["properties"].items():
            assert schema.get("description"), f"{tool.name}.{name} has no description"


def test_server_tells_the_agent_the_workflow() -> None:
    assert "sync_instruments" in (mcp_server.mcp.instructions or "")


def test_get_option_chain_reports_percent_units_and_exchange_local_expiry() -> None:
    from openticker.storage.sqlite.instruments_repo import upsert_instruments
    from tests.fixtures.options import NIFTY_INDEX, chain_contracts

    expiry = date(2099, 1, 1)  # far enough that the test's real clock never passes it
    upsert_instruments([NIFTY_INDEX] + chain_contracts("NIFTY", expiry, [2400.0, 2500.0, 2600.0]))

    result = mcp_server.get_option_chain(
        broker="fake",
        underlying="NIFTY 50",
        exchange=Exchange.NSE,
        strike_count=1,
        interest_rate=6.5,
    )

    assert result.atm_strike == 2500  # FakeBrokerPort quotes everything at 2500
    assert result.interest_rate == 6.5
    assert result.expires_at.isoformat() == "2099-01-01T15:30:00+05:30"
    assert result.available_expiries == [expiry]
    atm_call = result.rows[1].call
    assert atm_call is not None and atm_call.label == "ATM" and atm_call.greeks_model is not None


def test_get_option_chain_before_sync_is_an_agent_facing_error() -> None:
    with pytest.raises(ToolError, match="sync_instruments"):
        mcp_server.get_option_chain(broker="fake", underlying="NIFTY 50", exchange=Exchange.NSE)


def test_sandbox_round_trip_through_the_tools() -> None:
    mcp_server.sync_instruments(broker="fake")

    placed = mcp_server.place_order(
        broker="fake",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=4,
        product=Product.MIS,
    )
    positions = mcp_server.get_positions(broker="fake")
    funds = mcp_server.get_funds(broker="fake")
    book = mcp_server.get_orderbook(broker="fake")
    audit = mcp_server.get_audit_log(event_type="OrderFilled")

    assert (placed.status, placed.fill_price) == ("FILLED", FAKE_LAST_PRICE)
    assert [(p.symbol, p.quantity) for p in positions.positions] == [("RELIANCE", 4)]
    assert positions.total_unrealized_pnl == 0.0
    assert funds.used_margin == 4 * FAKE_LAST_PRICE / 5  # intraday equity: 5x leverage
    assert [order.order_id for order in book.orders] == [placed.order_id]
    assert audit.entries[0].triggered_by == "mcp"


def test_rejected_order_explains_itself_and_suggests_a_fix() -> None:
    mcp_server.sync_instruments(broker="fake")

    result = mcp_server.place_order(
        broker="fake",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.SELL,
        quantity=1,
        product=Product.CNC,
    )

    assert result.status == "REJECTED" and result.reason is not None
    assert "sold short" in result.reason
    assert result.next_step.startswith("Fix")


def test_evaluate_risk_tool_reports_wrong_side_settings() -> None:
    mcp_server.sync_instruments(broker="fake")

    result = mcp_server.evaluate_risk(
        broker="fake",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=1,
        stop_loss=FAKE_LAST_PRICE + 10,
    )

    assert result.breached and result.reason == "stop_loss" and result.warnings


def test_market_status_and_closed_market_orders(monkeypatch: pytest.MonkeyPatch) -> None:
    mcp_server.sync_instruments(broker="fake")
    monkeypatch.setattr(mcp_server, "clock", lambda: datetime(2026, 10, 2, 5, 0, tzinfo=UTC))

    [nse] = mcp_server.get_market_status(exchange=Exchange.NSE).exchanges
    placed = mcp_server.place_order(
        broker="fake",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=1,
        product=Product.MIS,
    )

    assert (nse.is_open, nse.closed_reason) == (False, "Mahatma Gandhi Jayanti")
    assert nse.session_opens_at.isoformat() == "2026-10-05T09:15:00+05:30"
    assert len(mcp_server.get_market_status().exchanges) == 5
    assert placed.status == "REJECTED" and placed.reason is not None
    assert "Mahatma Gandhi Jayanti" in placed.reason


def test_a_limit_order_rests_and_can_be_cancelled() -> None:
    from openticker.core.orders.models import OrderType

    mcp_server.sync_instruments(broker="fake")

    placed = mcp_server.place_order(
        broker="fake",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=2,
        product=Product.CNC,
        order_type=OrderType.LIMIT,
        price=FAKE_LAST_PRICE - 100,
    )
    assert placed.status == "PENDING" and placed.order_id is not None
    assert "openticker-serve" in placed.next_step
    [entry] = mcp_server.get_orderbook(broker="fake").orders
    assert (entry.status, entry.price) == ("PENDING", FAKE_LAST_PRICE - 100)

    cancelled = mcp_server.cancel_order(broker="fake", order_id=placed.order_id)

    assert cancelled.status == "CANCELLED"
    assert mcp_server.get_funds(broker="fake").used_margin == 0.0
    with pytest.raises(ToolError, match="no order"):
        mcp_server.cancel_order(broker="fake", order_id="SBNOPE")


STRADDLE_JSON = {
    "underlying": "NIFTY 50",
    "exchange": "NSE",
    "horizon": "intraday",
    "legs": [
        {"side": "SELL", "lots": 1, "option_type": "CE", "expiry": "weekly"},
        {"side": "SELL", "lots": 1, "option_type": "PE", "expiry": "weekly"},
    ],
    "entry_time": "09:20",
    "exit_time": "15:15",
    "combined_stop_loss": 3000,
    "lock_profit": {"arm_at": 2000, "lock": 1500},
}


def test_strategy_tools_round_trip_and_preview() -> None:
    from openticker.adapters.inbound.mcp_models import StrategyDefinition
    from tests.fixtures.strategies import list_nifty_market

    list_nifty_market()
    definition = StrategyDefinition.model_validate(STRADDLE_JSON)

    created = mcp_server.create_strategy(name="nifty straddle", definition=definition)
    fetched = mcp_server.get_strategy(strategy_id=created.strategy_id)
    preview = mcp_server.preview_strategy(broker="fake", strategy_id=created.strategy_id)

    assert fetched.definition == definition
    assert fetched.definition.lock_profit is not None
    assert fetched.definition.lock_profit.mode == "lock"
    assert "preview_strategy" in (created.next_step or "")
    assert [leg.symbol for leg in preview.legs] == ["NIFTY22SEP262500CE", "NIFTY22SEP262500PE"]
    assert [s.name for s in mcp_server.list_strategies().strategies] == ["nifty straddle"]

    changed = definition.model_copy(update={"combined_stop_loss": 2500.0})
    updated = mcp_server.update_strategy(
        strategy_id=created.strategy_id, name="nifty straddle", definition=changed
    )
    assert updated.definition.combined_stop_loss == 2500.0
    assert mcp_server.delete_strategy(strategy_id=created.strategy_id).deleted is True
    assert mcp_server.list_strategies().strategies == []


def test_strategy_tools_turn_mistakes_into_agent_facing_errors() -> None:
    from openticker.adapters.inbound.mcp_models import StrategyDefinition
    from tests.fixtures.strategies import list_nifty_market

    list_nifty_market()
    late = StrategyDefinition.model_validate({**STRADDLE_JSON, "exit_time": "15:25"})
    bad_lock = StrategyDefinition.model_validate(
        {**STRADDLE_JSON, "lock_profit": {"arm_at": 1000, "lock": 1500}}
    )
    good = StrategyDefinition.model_validate(STRADDLE_JSON)

    with pytest.raises(ToolError, match="squared off at 15:15"):
        mcp_server.create_strategy(name="late", definition=late)
    with pytest.raises(ToolError, match="below 1000"):
        mcp_server.create_strategy(name="bad lock", definition=bad_lock)
    mcp_server.create_strategy(name="taken", definition=good)
    with pytest.raises(ToolError, match="already exists"):
        mcp_server.create_strategy(name="taken", definition=good)
    with pytest.raises(ToolError, match="list_strategies"):
        mcp_server.get_strategy(strategy_id="stg_missing")


def test_strategy_definition_schema_describes_every_field() -> None:
    tool = next(tool for tool in _tools() if tool.name == "create_strategy")
    definitions = tool.input_schema["$defs"]

    for model in (
        "StrategyDefinition",
        "LegDefinition",
        "ProfitLockDefinition",
        "RiskValueInput",
    ):
        for name, schema in definitions[model]["properties"].items():
            assert schema.get("description"), f"{model}.{name} has no description"


def test_strategy_run_tools_start_watch_and_stop_a_run() -> None:
    from openticker.adapters.inbound.mcp_models import StrategyDefinition
    from openticker.use_cases.strategies.runner import process_commands
    from tests.fixtures.strategy_desk import Desk

    desk = Desk()
    desk.now = TRADING_TIME
    created = mcp_server.create_strategy(
        name="nifty straddle", definition=StrategyDefinition.model_validate(STRADDLE_JSON)
    )
    strategy_id = created.strategy_id

    started = mcp_server.start_strategy(broker="fake", strategy_id=strategy_id)
    assert (started.command, started.status) == ("start", "pending")
    assert "openticker-serve" in started.next_step
    process_commands(desk.context, desk.now)

    runs = mcp_server.get_strategy_runs(strategy_id=strategy_id)
    assert [(r.status, r.trigger) for r in runs.runs] == [("open", "mcp")]
    assert runs.commands[0].status == "done"
    assert isinstance(created.definition, StrategyDefinition)
    with pytest.raises(ToolError, match="stop the strategy before editing"):
        mcp_server.update_strategy(
            strategy_id=strategy_id, name="renamed", definition=created.definition
        )

    mcp_server.close_strategy_leg(strategy_id=strategy_id, leg_id="leg1")
    process_commands(desk.context, desk.now)
    run = mcp_server.get_strategy_run(run_id=runs.runs[0].run_id)
    assert [(leg.leg_id, leg.status) for leg in run.legs] == [("leg1", "closed"), ("leg2", "open")]
    assert [(o.leg_id, o.intent) for o in run.orders] == [
        ("leg1", "entry"),
        ("leg2", "entry"),
        ("leg1", "exit"),
    ]
    assert run.timeline[0].at.utcoffset() is not None

    killed = mcp_server.kill_strategy(strategy_id=strategy_id)
    assert killed.locked
    process_commands(desk.context, desk.now)
    ended = mcp_server.get_strategy_runs(strategy_id=strategy_id).runs[0]
    assert (ended.status, ended.stop_reason) == ("ended", "kill")
    with pytest.raises(ToolError, match="release_kill_switch"):
        mcp_server.start_strategy(broker="fake", strategy_id=strategy_id)
    assert mcp_server.release_kill_switch(strategy_id=strategy_id).locked is False


def test_schedule_tools_arm_and_disarm_scheduled_entries() -> None:
    from openticker.adapters.inbound.mcp_models import StrategyDefinition
    from tests.fixtures.strategies import list_nifty_market

    list_nifty_market()
    created = mcp_server.create_strategy(
        name="scheduled", definition=StrategyDefinition.model_validate(STRADDLE_JSON)
    )
    strategy_id = created.strategy_id
    assert created.scheduled_broker is None

    scheduled = mcp_server.schedule_strategy(broker="fake", strategy_id=strategy_id)
    assert scheduled.scheduled_broker == "fake" and "entry_time" in (scheduled.next_step or "")
    assert [s.scheduled for s in mcp_server.list_strategies().strategies] == [True]
    with pytest.raises(ToolError, match="no broker adapter registered"):
        mcp_server.schedule_strategy(broker="nope", strategy_id=strategy_id)

    assert mcp_server.unschedule_strategy(strategy_id=strategy_id).scheduled_broker is None
    unscheduled = dict(STRADDLE_JSON, entry_time=None)
    mcp_server.update_strategy(
        strategy_id=strategy_id,
        name="scheduled",
        definition=StrategyDefinition.model_validate(unscheduled),
    )
    with pytest.raises(ToolError, match="no entry_time"):
        mcp_server.schedule_strategy(broker="fake", strategy_id=strategy_id)


def test_strategy_run_tools_turn_mistakes_into_agent_facing_errors() -> None:
    from openticker.adapters.inbound.mcp_models import StrategyDefinition
    from tests.fixtures.strategies import list_nifty_market

    list_nifty_market()
    created = mcp_server.create_strategy(
        name="idle", definition=StrategyDefinition.model_validate(STRADDLE_JSON)
    )

    with pytest.raises(ToolError, match="not running"):
        mcp_server.stop_strategy(strategy_id=created.strategy_id)
    with pytest.raises(ToolError, match="not running"):
        mcp_server.close_strategy_leg(strategy_id=created.strategy_id, leg_id="leg1")
    with pytest.raises(ToolError, match="get_strategy_runs"):
        mcp_server.get_strategy_run(run_id="run_missing")
    with pytest.raises(ToolError, match="list_strategies"):
        mcp_server.start_strategy(broker="fake", strategy_id="stg_missing")


SIGNAL_JSON = {
    "horizon": "intraday",
    "direction": "both",
    "legs": [
        {"symbol": "reliance", "exchange": "NSE", "quantity": 10, "accepts": "long_only"},
        {
            "symbol": "NIFTY22SEP262500CE",
            "exchange": "NFO",
            "quantity": 65,
            "stop_loss": {"value": 20, "percent": True},
        },
    ],
    "entry_time": "09:30",
    "exit_time": "15:00",
    "combined_stop_loss": 2000,
}


def test_signal_strategy_tools_give_an_alert_url_and_show_its_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from openticker.adapters.inbound.mcp_models import SignalStrategyDefinition
    from openticker.use_cases.strategies.signals import accept_signal
    from tests.fixtures.strategies import list_nifty_market

    mcp_server.sync_instruments(broker="fake")
    list_nifty_market()
    monkeypatch.setenv("OPENTICKER_PUBLIC_URL", "https://alerts.example.org/")
    definition = SignalStrategyDefinition.model_validate(SIGNAL_JSON)

    created = mcp_server.create_signal_strategy(name="alerts", definition=definition)
    fetched = mcp_server.get_strategy(strategy_id=created.strategy_id)
    webhook = mcp_server.rotate_strategy_webhook(
        broker="fake", strategy_id=created.strategy_id, allowed_ips=["52.89.214.238"]
    )
    token = webhook.alert_path.rsplit("/", 1)[1]
    accept_signal(
        token, "52.89.214.238", b'{"action": "long_entry", "leg_id": "leg1"}', TRADING_TIME
    )
    signals = mcp_server.get_strategy_signals(strategy_id=created.strategy_id)

    assert created.kind == "signal" and "rotate_strategy_webhook" in (created.next_step or "")
    assert fetched.definition == definition.model_copy(
        update={
            "legs": [
                definition.legs[0].model_copy(update={"symbol": "RELIANCE"}),
                definition.legs[1],
            ]
        }
    )
    assert webhook.alert_path.startswith("/webhooks/strategies/otw_")
    assert webhook.alert_url == "https://alerts.example.org" + webhook.alert_path
    assert webhook.allowed_ips == ["52.89.214.238/32"]
    assert signals.webhook is not None and signals.webhook.broker == "fake"
    assert [(c.result, c.commands[0].action) for c in signals.calls] == [("accepted", "long_entry")]
    summary = mcp_server.list_strategies().strategies[0]
    assert (summary.kind, summary.underlying) == ("signal", "RELIANCE, NIFTY22SEP262500CE")
    assert mcp_server.disable_strategy_webhook(strategy_id=created.strategy_id).kind == "signal"
    assert mcp_server.get_strategy_signals(strategy_id=created.strategy_id).webhook is None


def test_signal_strategy_tools_turn_mistakes_into_agent_facing_errors() -> None:
    from openticker.adapters.inbound.mcp_models import (
        SignalStrategyDefinition,
        StrategyDefinition,
    )
    from tests.fixtures.strategies import list_nifty_market

    mcp_server.sync_instruments(broker="fake")
    list_nifty_market()
    signal = mcp_server.create_signal_strategy(
        name="alerts", definition=SignalStrategyDefinition.model_validate(SIGNAL_JSON)
    )
    options = mcp_server.create_strategy(
        name="straddle", definition=StrategyDefinition.model_validate(STRADDLE_JSON)
    )

    with pytest.raises(ToolError, match="nothing to start"):
        mcp_server.start_strategy(broker="fake", strategy_id=signal.strategy_id)
    with pytest.raises(ToolError, match="is an options strategy"):
        mcp_server.rotate_strategy_webhook(broker="fake", strategy_id=options.strategy_id)
    with pytest.raises(ToolError, match="not an IP address"):
        mcp_server.rotate_strategy_webhook(
            broker="fake", strategy_id=signal.strategy_id, allowed_ips=["somewhere"]
        )
    with pytest.raises(ToolError, match="keeps its kind"):
        mcp_server.update_signal_strategy(
            strategy_id=options.strategy_id,
            name="straddle",
            definition=SignalStrategyDefinition.model_validate(SIGNAL_JSON),
        )
    with pytest.raises(ToolError, match="has no alert URL"):
        mcp_server.disable_strategy_webhook(strategy_id=signal.strategy_id)
    with pytest.raises(ToolError, match="not in the instrument master"):
        mcp_server.create_signal_strategy(
            name="unknown",
            definition=SignalStrategyDefinition.model_validate(
                {**SIGNAL_JSON, "legs": [{"symbol": "INFY", "exchange": "NSE", "quantity": 1}]}
            ),
        )


def test_signal_strategy_schema_describes_every_field() -> None:
    tool = next(tool for tool in _tools() if tool.name == "create_signal_strategy")
    definitions = tool.input_schema["$defs"]

    for model in ("SignalStrategyDefinition", "SignalLegDefinition"):
        for name, schema in definitions[model]["properties"].items():
            assert schema.get("description"), f"{model}.{name} has no description"
