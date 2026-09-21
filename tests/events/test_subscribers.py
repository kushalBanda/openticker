import json
from datetime import UTC, datetime

import pytest

from openticker.events.subscribers.audit_log import record_event
from openticker.events.subscribers.notifications import describe, notifier
from openticker.events.types import InstrumentSyncCompleted, OrderPlaced, RiskBreached
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
            order_id="42", symbol="RELIANCE", side="BUY", quantity=5, triggered_by="mcp",
            occurred_at=at,
        )
    )

    [entry] = list_audit(limit=10)

    assert entry.event_type == "OrderPlaced"
    assert entry.triggered_by == "mcp"
    assert entry.occurred_at == at
    assert json.loads(entry.payload) == {
        "order_id": "42", "symbol": "RELIANCE", "side": "BUY", "quantity": 5,
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
