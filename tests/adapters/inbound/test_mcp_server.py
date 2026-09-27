"""MCP tools end to end — tool -> registry -> use case -> port -> storage ->
response — with `FakeBrokerPort` registered under its own name, so nothing
touches Kite."""

import asyncio
import json
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import Tool

from openticker.adapters.brokers import registry
from openticker.adapters.inbound import mcp_server
from openticker.adapters.inbound.mcp_scoped import as_client
from openticker.ports.models import Exchange, InstrumentType, Interval, Product, Side
from openticker.use_cases import agent_clients
from tests.fixtures.fake_broker import FAKE_ASK, FAKE_LAST_PRICE, FakeBrokerPort

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


def test_get_market_depth_through_the_tool() -> None:
    mcp_server.sync_instruments(broker="fake")

    depth = mcp_server.get_market_depth(broker="fake", symbol="RELIANCE", exchange=Exchange.NSE)

    assert (depth.symbol, depth.last_price, depth.last_quantity) == ("RELIANCE", FAKE_LAST_PRICE, 5)
    assert [a.price for a in depth.asks] == [FAKE_LAST_PRICE + 0.05]
    assert depth.as_of.utcoffset() is not None
    with pytest.raises(ToolError, match="sync_instruments"):
        mcp_server.get_market_depth(broker="fake", symbol="NOPE", exchange=Exchange.NSE)


def test_get_quotes_through_the_tool() -> None:
    mcp_server.sync_instruments(broker="fake")

    from openticker.adapters.inbound.mcp_models import InstrumentRef

    result = mcp_server.get_quotes(
        broker="fake",
        instruments=[
            InstrumentRef(symbol="RELIANCE", exchange=Exchange.NSE),
            InstrumentRef(symbol="NOPE", exchange=Exchange.NSE),
        ],
    )

    assert [(q.symbol, q.last_price) for q in result.quotes] == [("RELIANCE", FAKE_LAST_PRICE)]
    assert [m.symbol for m in result.missing] == ["NOPE"]
    with pytest.raises(ToolError, match="sync_instruments"):
        mcp_server.get_quotes(
            broker="fake", instruments=[InstrumentRef(symbol="NOPE", exchange=Exchange.NSE)]
        )


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


def test_object_parameters_are_inline_so_every_client_sees_an_object() -> None:
    """A parameter that is only a `$ref` has no `type`; MCP Inspector then
    offers a text box and sends a string, which validation refuses."""
    for tool in _tools():
        defs = tool.input_schema.get("$defs", {})
        for name, schema in tool.input_schema["properties"].items():
            for option in schema.get("anyOf", [schema]):
                ref = option.get("$ref", "")
                target = defs.get(ref.removeprefix("#/$defs/"), {})
                assert target.get("type") != "object", f"{tool.name}.{name} is a $ref to an object"


def test_times_are_plain_hh_mm_in_every_schema() -> None:
    """JSON Schema's "time" format requires a UTC offset; clients that check
    formats would refuse "09:20", the exchange-local time these fields take."""
    for tool in _tools():
        for schema in (tool.input_schema, tool.output_schema):
            assert '"format": "time"' not in json.dumps(schema), tool.name
    tool = next(tool for tool in _tools() if tool.name == "schedule_script")
    pattern = re.compile(
        tool.input_schema["properties"]["schedule"]["properties"]["start_time"]["pattern"]
    )
    assert [bool(pattern.match(t)) for t in ("09:20", "15:15:00", "9:20", "24:00", "09:20Z")] == [
        True,
        True,
        False,
        False,
        False,
    ]


def test_an_inlined_parameter_still_validates_as_its_model() -> None:
    call = mcp_server.mcp.call_tool(
        "schedule_script",
        {"script_id": "scr_missing", "schedule": {"start_time": "09:20"}},
    )
    with pytest.raises(ToolError, match="no script 'scr_missing'"):
        asyncio.run(call)
    bad = mcp_server.mcp.call_tool(
        "schedule_script", {"script_id": "scr_missing", "schedule": "long_only"}
    )
    with pytest.raises(ToolError, match="schedule"):
        asyncio.run(bad)


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

    assert (placed.status, placed.fill_price) == ("FILLED", FAKE_ASK)  # a buy pays the ask
    assert [(p.symbol, p.quantity) for p in positions.positions] == [("RELIANCE", 4)]
    assert positions.total_unrealized_pnl == pytest.approx(4 * (FAKE_LAST_PRICE - FAKE_ASK))
    assert funds.used_margin == round(4 * FAKE_ASK / 5, 2)  # intraday equity: 5x leverage
    assert funds.charges > 0
    assert funds.available_cash == pytest.approx(
        funds.total_capital - funds.used_margin - funds.charges
    )
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


def test_every_nested_field_of_every_tool_is_described() -> None:
    """Strategy definitions, their legs and limits, script schedules: every
    field an agent fills in says what it is."""

    def objects(node: object) -> Iterator[dict[str, Any]]:
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                yield node
            for value in node.values():
                yield from objects(value)
        elif isinstance(node, list):
            for value in node:
                yield from objects(value)

    checked = set()
    for tool in _tools():
        for name, schema in tool.input_schema["properties"].items():
            for nested in objects(schema):
                checked.add(nested.get("title"))
                for field, field_schema in nested["properties"].items():
                    assert field_schema.get("description"), f"{tool.name}.{name}: {field}"
    assert {
        "StrategyDefinition",
        "LegDefinition",
        "ProfitLockDefinition",
        "RiskValueInput",
        "SignalStrategyDefinition",
        "SignalLegDefinition",
        "ScriptScheduleDefinition",
    } <= checked


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
    ledger = mcp_server.get_strategy_ledger(strategy_id=strategy_id)
    # The test desk charges nothing, so its run can't be judged after costs.
    assert (ledger.total_runs, ledger.uncharged, ledger.totals.runs) == (1, 1, 0)
    assert [len(r.fills) for r in ledger.runs] == [4]
    assert ledger.runs[0].started_at.utcoffset() == timedelta(hours=5, minutes=30)
    with pytest.raises(ToolError, match="list_strategies"):
        mcp_server.get_strategy_ledger(strategy_id="stg_nope")
    with pytest.raises(ToolError, match="release_kill_switch"):
        mcp_server.start_strategy(broker="fake", strategy_id=strategy_id)
    assert mcp_server.release_kill_switch(strategy_id=strategy_id).locked is False


def test_review_tools_queue_a_job_and_read_it_back() -> None:
    from openticker.adapters.inbound.mcp_models import StrategyDefinition
    from tests.fixtures.strategies import list_nifty_market

    list_nifty_market()
    strategy_id = mcp_server.create_strategy(
        name="reviewed", definition=StrategyDefinition.model_validate(STRADDLE_JSON)
    ).strategy_id

    started = mcp_server.start_review(strategy_id=strategy_id)
    jobs = mcp_server.get_agent_jobs(strategy_id=strategy_id)
    log = mcp_server.get_agent_job_log(job_id=started.job.job_id)

    assert (started.job.status, started.job.harness, started.job.trigger) == (
        "pending",
        "claude",
        "mcp",
    )
    assert "openticker-serve" in started.next_step
    assert [job.job_id for job in jobs.jobs] == [started.job.job_id]
    assert (log.status, log.log, log.truncated) == ("pending", "", False)
    with pytest.raises(ToolError, match="already pending"):
        mcp_server.start_review(strategy_id=strategy_id)
    with pytest.raises(ToolError, match="get_agent_jobs lists them"):
        mcp_server.get_agent_job_log(job_id="job_nope")


def test_review_schedule_tools_set_show_and_clear_it() -> None:
    from openticker.adapters.inbound.mcp_models import StrategyDefinition
    from tests.fixtures.strategies import list_nifty_market

    list_nifty_market()
    strategy_id = mcp_server.create_strategy(
        name="reviewed", definition=StrategyDefinition.model_validate(STRADDLE_JSON)
    ).strategy_id

    scheduled = mcp_server.schedule_review(strategy_id=strategy_id, every="1d", drawdown=3_000)
    listed = mcp_server.list_strategies().strategies

    assert scheduled.review_schedule is not None
    assert (scheduled.review_schedule.every, scheduled.review_schedule.after_runs) == ("1d", None)
    assert scheduled.review_schedule.drawdown == 3_000
    assert [s.review_scheduled for s in listed] == [True]
    with pytest.raises(ToolError, match="like 30m, 4h or 1d"):
        mcp_server.schedule_review(strategy_id=strategy_id, every="weekly")
    assert mcp_server.unschedule_review(strategy_id=strategy_id).review_schedule is None


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


def test_script_tools_upload_run_and_read_a_script() -> None:
    from openticker.adapters.inbound.mcp_models import ScriptScheduleDefinition
    from openticker.core.scripts.models import ScriptLimits
    from openticker.storage import script_files
    from openticker.use_cases.scripts.supervise import (
        SupervisorContext,
        process_script_commands,
        watch_scripts,
    )
    from tests.fixtures.calendar import NO_HOLIDAYS
    from tests.fixtures.fake_processes import FakeProcesses

    processes = FakeProcesses()
    context = SupervisorContext(
        processes, mcp_server.event_bus(), NO_HOLIDAYS, ScriptLimits(), "http://127.0.0.1:8750"
    )
    uploaded = mcp_server.upload_script(name="pinger", source="print('ping')\n")
    script_id = uploaded.script_id
    assert (uploaded.running, uploaded.last_run, uploaded.schedule) == (False, None, None)
    assert "start_script" in (uploaded.next_step or "")

    started = mcp_server.start_script(script_id=script_id)
    assert (started.command.command, started.command.status) == ("start", "pending")
    process_script_commands(context, TRADING_TIME)
    (listed,) = mcp_server.list_scripts().scripts
    assert listed.running
    assert listed.last_run is not None and listed.last_run.trigger == "mcp"
    run_id = listed.last_run.run_id
    with pytest.raises(ToolError, match="stop_script it before changing it"):
        mcp_server.update_script(script_id=script_id, name="pinger", source="print(1)\n")

    script_files.append_log(script_id, run_id, "ping")
    mcp_server.stop_script(script_id=script_id)
    process_script_commands(context, TRADING_TIME)
    watch_scripts(context, TRADING_TIME)
    logs = mcp_server.get_script_logs(script_id=script_id)
    assert logs.run.run_id == run_id
    assert logs.run.stop_reason == "stopped"
    assert logs.lines[1] == "ping"
    assert logs.run.started_at.utcoffset() is not None

    detail = mcp_server.get_script(script_id=script_id, include_source=True)
    assert detail.source == "print('ping')\n"
    assert [c.command for c in detail.commands] == ["stop", "start"]
    scheduled = mcp_server.schedule_script(
        script_id=script_id,
        schedule=ScriptScheduleDefinition.model_validate({"start_time": "09:20"}),
    )
    assert scheduled.schedule is not None and scheduled.schedule.weekdays == [0, 1, 2, 3, 4]
    assert mcp_server.unschedule_script(script_id=script_id).schedule is None
    assert mcp_server.delete_script(script_id=script_id).deleted
    assert mcp_server.list_scripts().scripts == []


def test_script_tools_turn_mistakes_into_agent_facing_errors() -> None:
    from openticker.adapters.inbound.mcp_models import ScriptScheduleDefinition

    with pytest.raises(ToolError, match="not valid Python"):
        mcp_server.upload_script(name="bad", source="def (:\n")
    script_id = mcp_server.upload_script(name="ok", source="pass\n").script_id
    with pytest.raises(ToolError, match="already exists"):
        mcp_server.upload_script(name="ok", source="pass\n")
    with pytest.raises(ToolError, match="not running; nothing to stop"):
        mcp_server.stop_script(script_id=script_id)
    with pytest.raises(ToolError, match="has never run"):
        mcp_server.get_script_logs(script_id=script_id)
    with pytest.raises(ToolError, match="list_scripts shows them"):
        mcp_server.start_script(script_id="scr_missing")
    with pytest.raises(ToolError, match="must be after start_time"):
        mcp_server.schedule_script(
            script_id=script_id,
            schedule=ScriptScheduleDefinition.model_validate(
                {"start_time": "10:00", "stop_time": "09:00"}
            ),
        )


def test_modify_order_through_the_tool() -> None:
    from openticker.core.orders.models import OrderType

    mcp_server.sync_instruments(broker="fake")
    placed = mcp_server.place_order(
        broker="fake",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.SELL,
        quantity=3,
        product=Product.MIS,
        order_type=OrderType.SL_M,
        trigger_price=2400.0,
    )
    assert placed.order_id is not None

    moved = mcp_server.modify_order(broker="fake", order_id=placed.order_id, trigger_price=2390.0)
    refused = mcp_server.modify_order(broker="fake", order_id=placed.order_id, price=2390.0)

    assert moved.status == "PENDING" and moved.order is not None
    assert (moved.order.trigger_price, moved.order.status) == (2390.0, "PENDING")
    assert refused.status == "REJECTED" and refused.reason == "SL-M orders take no price"
    assert "cancel_order" in refused.next_step
    with pytest.raises(ToolError, match="get_orderbook"):
        mcp_server.modify_order(broker="fake", order_id="SBNOPE", price=1.0)


def test_place_basket_through_the_tool() -> None:
    from openticker.adapters.inbound.mcp_models import OrderInput

    mcp_server.sync_instruments(broker="fake")
    leg = {"symbol": "RELIANCE", "exchange": Exchange.NSE, "quantity": 2, "product": Product.MIS}

    result = mcp_server.place_basket(
        broker="fake",
        orders=[
            OrderInput(side=Side.SELL, **leg),  # type: ignore[arg-type]
            OrderInput(side=Side.BUY, **{**leg, "symbol": "NOPE"}),  # type: ignore[arg-type]
            OrderInput(side=Side.BUY, **leg),  # type: ignore[arg-type]
        ],
    )

    assert [(o.symbol, o.side, o.status) for o in result.orders] == [
        ("NOPE", Side.BUY, "REJECTED"),
        ("RELIANCE", Side.BUY, "FILLED"),
        ("RELIANCE", Side.SELL, "FILLED"),
    ]
    assert "sync_instruments" in (result.orders[0].reason or "")
    assert "get_positions" in result.orders[1].next_step
    assert mcp_server.get_positions(broker="fake").positions == []


def test_close_and_cancel_all_through_the_tools() -> None:
    from openticker.core.orders.models import OrderType

    mcp_server.sync_instruments(broker="fake")
    for product, order_type, price in (
        (Product.MIS, OrderType.MARKET, None),
        (Product.CNC, OrderType.MARKET, None),
        (Product.MIS, OrderType.LIMIT, 2000.0),
    ):
        mcp_server.place_order(
            broker="fake",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=Side.BUY,
            quantity=2,
            product=product,
            order_type=order_type,
            price=price,
        )

    one = mcp_server.close_position(
        broker="fake", symbol="RELIANCE", exchange=Exchange.NSE, product=Product.MIS
    )
    rest = mcp_server.close_all_positions(broker="fake")
    cancelled = mcp_server.cancel_all_orders(broker="fake")

    assert (one.side, one.quantity, one.status) == (Side.SELL, 2, "FILLED")
    assert "get_positions" in one.next_step
    assert [(o.symbol, o.status) for o in rest.orders] == [("RELIANCE", "FILLED")]
    assert len(cancelled.cancelled) == 1
    assert mcp_server.get_positions(broker="fake").positions == []
    with pytest.raises(ToolError, match="get_positions"):
        mcp_server.close_position(
            broker="fake", symbol="RELIANCE", exchange=Exchange.NSE, product=Product.MIS
        )


def test_get_margin_through_the_tool() -> None:
    from openticker.adapters.inbound.mcp_models import OrderInput

    mcp_server.sync_instruments(broker="fake")

    one = mcp_server.get_margin(
        broker="fake",
        orders=[
            OrderInput(
                symbol="RELIANCE",
                exchange=Exchange.NSE,
                side=Side.SELL,
                quantity=10,
                product=Product.MIS,
            )
        ],
    )

    assert (one.total, one.benefit) == (10 * FAKE_LAST_PRICE * 0.2, 0.0)
    with pytest.raises(ToolError, match="order 1: no instrument 'NOPE'"):
        mcp_server.get_margin(
            broker="fake",
            orders=[
                OrderInput(
                    symbol="NOPE",
                    exchange=Exchange.NSE,
                    side=Side.BUY,
                    quantity=1,
                    product=Product.MIS,
                )
            ],
        )


def test_order_status_and_tradebook_through_the_tools() -> None:
    mcp_server.sync_instruments(broker="fake")
    placed = mcp_server.place_order(
        broker="fake",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=3,
        product=Product.MIS,
    )
    assert placed.order_id is not None

    status = mcp_server.get_order_status(broker="fake", order_id=placed.order_id)
    book = mcp_server.get_tradebook(broker="fake")

    assert (status.status, status.fill_price) == ("FILLED", FAKE_ASK)
    assert book.trades[0].expected_price == FAKE_LAST_PRICE
    assert book.trades[0].charges is not None and book.trades[0].charges > 0
    assert [(t.order_id, t.quantity, t.triggered_by) for t in book.trades] == [
        (placed.order_id, 3, "mcp")
    ]
    assert book.trades[0].filled_at == TRADING_TIME  # the server's clock, not the wall's
    trade = book.trades[0]
    assert trade.realized_pnl == 0.0 and trade.charges_detail is not None
    assert round(sum(trade.charges_detail.values()), 2) == trade.charges
    assert (trade.source, trade.placed_by, trade.instrument_type) == ("agent", None, "EQ")
    month = mcp_server.get_tradebook(broker="fake", period="month")
    assert len(month.trades) == 1 and month.since.day == 1
    with pytest.raises(ToolError, match="get_orderbook"):
        mcp_server.get_order_status(broker="fake", order_id="SBNOPE")


def test_orderbook_says_who_placed_each_and_can_keep_to_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp_server.sync_instruments(broker="fake")
    placed = mcp_server.place_order(
        broker="fake",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=3,
        product=Product.MIS,
    )

    [order] = mcp_server.get_orderbook(broker="fake", today_only=True).orders
    monkeypatch.setattr(mcp_server, "clock", lambda: TRADING_TIME + timedelta(days=1))
    tomorrow = mcp_server.get_orderbook(broker="fake", today_only=True).orders
    everything = mcp_server.get_orderbook(broker="fake").orders

    assert (order.order_id, order.source, order.placed_by) == (placed.order_id, "agent", None)
    assert (order.instrument_type, order.lot_size, order.triggered) == ("EQ", 1, False)
    assert tomorrow == [] and len(everything) == 1


def test_preview_paper_margin_through_the_tool() -> None:
    mcp_server.sync_instruments(broker="fake")

    margin = mcp_server.preview_paper_margin(
        broker="fake",
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=10,
        product=Product.CNC,
        price=2500.0,
    )

    assert (margin.required, margin.released, margin.fits) == (25_000.0, 0.0, True)
    with pytest.raises(ToolError, match="NOPE"):
        mcp_server.preview_paper_margin(
            broker="fake",
            symbol="NOPE",
            exchange=Exchange.NSE,
            side=Side.BUY,
            quantity=1,
            product=Product.CNC,
            price=1.0,
        )


def test_check_charge_rates_through_the_tool() -> None:
    mcp_server.sync_instruments(broker="fake")  # RELIANCE on NSE only

    checked = mcp_server.check_charge_rates(broker="fake")

    assert checked.matches and checked.next_step.startswith("Nothing to do")
    assert {(s.segment, s.side) for s in checked.samples} == {
        ("equity_delivery", Side.BUY),
        ("equity_delivery", Side.SELL),
        ("equity_intraday", Side.BUY),
        ("equity_intraday", Side.SELL),
    }
    assert all(s.ours == s.broker and s.differences == [] for s in checked.samples)
    assert "futures on NFO: no NIFTY future listed" in checked.skipped
    assert checked.checked_at.utcoffset() == timedelta(hours=5, minutes=30)


def test_check_charge_rates_before_any_sync_says_why() -> None:
    with pytest.raises(ToolError, match="RELIANCE is not in the instrument list"):
        mcp_server.check_charge_rates(broker="fake")


def test_preview_charges_through_the_tool() -> None:
    mcp_server.sync_instruments(broker="fake")

    bought = mcp_server.preview_charges(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=10,
        price=1226.0,
        product=Product.MIS,
    )
    sold = mcp_server.preview_charges(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        side=Side.SELL,
        quantity=10,
        price=1226.0,
        product=Product.MIS,
    )

    assert (bought.segment, bought.total, sold.total) == ("equity_intraday", 4.80, 7.86)
    assert sold.items["transaction_tax"] > 0 and bought.items["transaction_tax"] == 0
    assert bought.rates_source.startswith("https://zerodha.com")
    with pytest.raises(ToolError, match="no instrument 'NOPE'"):
        mcp_server.preview_charges(
            symbol="NOPE",
            exchange=Exchange.NSE,
            side=Side.BUY,
            quantity=1,
            price=1.0,
            product=Product.MIS,
        )


@pytest.fixture
def _fresh_client_notes() -> Iterator[None]:
    agent_clients.forget_noted()
    yield
    agent_clients.forget_noted()


@pytest.mark.usefixtures("_fresh_client_notes")
def test_orders_record_mcp_client_name() -> None:
    from mcp.client import Client
    from mcp.types import Implementation

    mcp_server.sync_instruments(broker="fake")

    async def place() -> None:
        info = Implementation(name="Claude Code", version="2.1.0")
        async with Client(mcp_server.mcp, client_info=info) as client:
            arguments = {
                "broker": "fake",
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "side": "BUY",
                "quantity": 1,
                "product": "MIS",
            }
            await client.call_tool("place_order", arguments)

    asyncio.run(place())
    audit = mcp_server.get_audit_log(event_type="OrderFilled")
    clients = agent_clients.get_agent_clients()

    assert audit.entries[0].triggered_by == "mcp:claude-code"
    assert [(c.name, c.transport, c.version, c.calls) for c in clients] == [
        ("claude-code", "stdio", "2.1.0", 1)
    ]


def test_unknown_client_records_plain_mcp() -> None:
    mcp_server.sync_instruments(broker="fake")
    with as_client(None):
        mcp_server.place_order(
            broker="fake",
            symbol="RELIANCE",
            exchange=Exchange.NSE,
            side=Side.BUY,
            quantity=1,
            product=Product.MIS,
        )

    assert mcp_server.get_audit_log(event_type="OrderFilled").entries[0].triggered_by == "mcp"


@pytest.mark.usefixtures("_fresh_client_notes")
def test_client_noted_once_a_minute() -> None:
    for seconds in (0, 30, 59):
        agent_clients.note_agent_client(
            "codex", "stdio", "1", TRADING_TIME + timedelta(seconds=seconds)
        )
    first = agent_clients.get_agent_clients()
    agent_clients.note_agent_client("codex", "stdio", "1", TRADING_TIME + timedelta(seconds=61))
    second = agent_clients.get_agent_clients()

    assert [c.calls for c in first] == [1]  # the two after it wait for the next write
    assert [(c.calls, c.last_seen_at) for c in second] == [
        (4, TRADING_TIME + timedelta(seconds=61))
    ]
