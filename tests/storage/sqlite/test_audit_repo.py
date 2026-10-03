from datetime import UTC, datetime, timedelta

from openticker.core.pnl import Source, source_of
from openticker.storage.sqlite.audit_repo import list_audit, write_audit

AT = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)
TRIGGERS = [
    "ui",
    "mcp",
    "mcp:claude-code",
    "mcp:codex",
    "mcp:cursor",
    "mcp:claude-code-beta",
    "review:s1",
    "strategy:s1",
    "webhook",
    "alert:s1",
    "script:abc",
    "schedule",
    "schedule: every 5 runs",
    "rest:laptop",
    "margin",
    "square-off",
    None,
    "100%_odd",
]


def test_filtering_by_source_agrees_with_source_of() -> None:
    for trigger in TRIGGERS:
        write_audit("OrderPlaced", AT, trigger, "{}")
    everything = list_audit(100)

    for source in Source:
        expected = [e.id for e in everything if source_of(e.triggered_by) is source]
        assert [e.id for e in list_audit(100, source=source)] == expected, source


def test_pages_back_by_id_and_reads_forward_from_one() -> None:
    for minute in range(5):
        write_audit("OrderPlaced", AT + timedelta(minutes=minute), "ui", "{}")
    ids = [e.id for e in list_audit(10)]  # newest first

    older = list_audit(2, before_id=ids[1])
    forward = list_audit(10, after_id=ids[2], oldest_first=True)

    assert [e.id for e in older] == ids[2:4]
    assert [e.id for e in forward] == [ids[1], ids[0]]


def test_filters_by_kinds_and_time() -> None:
    write_audit("OrderFilled", AT - timedelta(days=1), "ui", "{}")
    write_audit("OrderFilled", AT, "ui", "{}")
    write_audit("StrategyStopped", AT, "strategy:s1", "{}")
    write_audit("InstrumentSyncCompleted", AT, None, "{}")

    kinds = list_audit(10, event_types=["OrderFilled", "StrategyStopped"], since=AT)

    assert [e.event_type for e in kinds] == ["StrategyStopped", "OrderFilled"]
