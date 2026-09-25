import json
from datetime import UTC, datetime

import pytest

from openticker.events.subscribers.audit_log import record_event
from openticker.events.subscribers.notifications import NOTIFIED_EVENTS, describe, notifier
from openticker.events.types import (
    InstrumentSyncCompleted,
    OrderPlaced,
    RiskBreached,
    StrategyLegClosed,
    StrategyStarted,
    StrategyStopped,
)
from openticker.storage.sqlite.audit_repo import list_audit


class _Channel:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self._fail = fail

    def send(self, subject: str, message: str) -> None:
        if self._fail:
            raise ConnectionError("channel down")
        self.sent.append((subject, message))


def test_audit_records_type_trigger_time_and_fields() -> None:
    at = datetime(2026, 9, 21, 4, 0, tzinfo=UTC)
    record_event(
        OrderPlaced(
            order_id="42",
            symbol="RELIANCE",
            side="BUY",
            quantity=5,
            triggered_by="mcp",
            occurred_at=at,
        )
    )

    [entry] = list_audit(limit=10)

    assert entry.event_type == "OrderPlaced"
    assert entry.triggered_by == "mcp"
    assert entry.occurred_at == at
    assert json.loads(entry.payload) == {
        "order_id": "42",
        "symbol": "RELIANCE",
        "side": "BUY",
        "quantity": 5,
        "triggered_by": "mcp",
    }


def test_audit_log_is_most_recent_first_and_filterable() -> None:
    record_event(InstrumentSyncCompleted(broker="zerodha", count=1))
    record_event(RiskBreached(symbol="RELIANCE", reason="target", detail="target hit"))

    assert [e.event_type for e in list_audit(10)] == ["RiskBreached", "InstrumentSyncCompleted"]
    assert [e.event_type for e in list_audit(10, "InstrumentSyncCompleted")] == [
        "InstrumentSyncCompleted"
    ]


def test_describe_skips_events_not_worth_a_notification() -> None:
    assert describe(InstrumentSyncCompleted(broker="zerodha", count=1)) is None
    subject, message = describe(
        RiskBreached(symbol="NIFTY22SEP2623350CE", reason="stop_loss", detail="stop loss hit")
    ) or ("", "")
    assert subject == "Risk breached: NIFTY22SEP2623350CE (stop_loss)"
    assert message == "stop loss hit"


def test_one_failing_channel_does_not_silence_the_others() -> None:
    working = _Channel()
    notify = notifier([_Channel(fail=True), working])

    with pytest.raises(ExceptionGroup):
        notify(RiskBreached(symbol="RELIANCE", reason="stop_loss", detail="hit"))

    assert working.sent == [("Risk breached: RELIANCE (stop_loss)", "hit")]


def test_a_fill_is_notified_but_the_placement_before_it_is_not() -> None:
    from openticker.events.types import OrderFilled

    placed = OrderPlaced(
        order_id="SB1", symbol="RELIANCE", side="BUY", quantity=4, triggered_by="mcp"
    )
    filled = OrderFilled(
        order_id="SB1", symbol="RELIANCE", side="BUY", quantity=4, price=1374.6, triggered_by="mcp"
    )

    assert describe(placed) is None
    assert OrderFilled in NOTIFIED_EVENTS and OrderPlaced not in NOTIFIED_EVENTS
    assert describe(filled) == (
        "Order filled: BUY 4 RELIANCE @ 1,374.60",
        "Sandbox order SB1 filled via mcp.",
    )


def test_a_refused_broker_session_asks_the_user_to_log_in() -> None:
    from openticker.events.types import BrokerSessionExpired

    event = BrokerSessionExpired(broker="zerodha", detail="log in again")

    assert BrokerSessionExpired in NOTIFIED_EVENTS
    assert describe(event) == ("Log in to zerodha: live prices stopped", "log in again")


def test_differing_charge_rates_are_notified_with_where_to_fix_them() -> None:
    from openticker.events.types import ChargeRatesDiffer

    event = ChargeRatesDiffer(
        broker="zerodha",
        rates_as_of="2026-09-25",
        differing=1,
        checked=16,
        detail="options SELL 65 NIFTY29SEP2625000CE (NFO) @ 86.70: "
        "transaction_tax ours 8.45, broker 9.10",
        triggered_by="daemon",
    )

    assert ChargeRatesDiffer in NOTIFIED_EVENTS
    subject, message = describe(event) or ("", "")
    assert subject == "Charge rates differ from zerodha's: 1 of 16 samples"
    assert "transaction_tax ours 8.45, broker 9.10" in message
    assert "dated 2026-09-25" in message and "$OPENTICKER_HOME/charges.json" in message


def test_an_ended_review_leads_with_its_verdict_and_a_failed_one_with_why() -> None:
    from openticker.events.types import AgentJobEnded

    finished = AgentJobEnded(
        job_id="job_1",
        kind="review",
        strategy_id="stg_1",
        strategy_name="nifty condor",
        reason="finished",
        detail="exited with code 0",
        summary="Retire: the test is met.\nWorst run -3,259.",
        cost_usd=0.38,
    )
    timed_out = AgentJobEnded(
        job_id="job_2",
        kind="review",
        strategy_id="stg_1",
        strategy_name="nifty condor",
        reason="timeout",
        detail="still running after 15 minutes",
        summary=None,
        cost_usd=None,
    )

    assert AgentJobEnded in NOTIFIED_EVENTS
    subject, message = describe(finished) or ("", "")
    assert subject == "Review of nifty condor: Retire: the test is met."
    assert "Worst run -3,259." in message and "Cost $0.38." in message
    subject, message = describe(timed_out) or ("", "")
    assert subject == "Review of nifty condor timeout"
    assert "still running after 15 minutes" in message and "get_agent_job_log" in message


def test_a_strategy_start_leg_exit_and_stop_are_notified() -> None:
    started = StrategyStarted(
        strategy_id="stg_1",
        run_id="run_1",
        name="straddle",
        legs="SELL 65 X @ 100.0",
        triggered_by="mcp",
    )
    leg = StrategyLegClosed(
        strategy_id="stg_1",
        run_id="run_1",
        leg_id="leg1",
        symbol="X",
        reason="stop_loss",
        detail="stop_loss: exit filled",
        realized_pnl=-1365.0,
    )
    stopped = StrategyStopped(
        strategy_id="stg_1",
        run_id="run_1",
        name="straddle",
        reason="combined_stop_loss",
        detail="P&L -3,250.00 reached the combined stop loss -3,000.00",
        realized_pnl=-3250.0,
    )

    assert {StrategyStarted, StrategyLegClosed, StrategyStopped} <= set(NOTIFIED_EVENTS)
    assert describe(started) == ("Strategy started: straddle", "Entered SELL 65 X @ 100.0.")
    assert describe(leg) == (
        "Strategy leg closed: X (stop_loss), P&L -1,365.00",
        "stop_loss: exit filled",
    )
    assert describe(stopped) == (
        "Strategy stopped: straddle (combined_stop_loss), P&L -3,250.00",
        "P&L -3,250.00 reached the combined stop loss -3,000.00",
    )
