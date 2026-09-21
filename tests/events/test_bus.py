import logging
import threading

import pytest

from openticker.events.bus import EventBus
from openticker.events.types import InstrumentSyncCompleted, RiskBreached

_EVENT = RiskBreached(symbol="RELIANCE", reason="stop_loss", detail="stop loss 95 hit at 94")


def test_inline_subscriber_runs_before_publish_returns() -> None:
    bus = EventBus()
    seen: list[RiskBreached] = []
    bus.subscribe(RiskBreached, seen.append, background=False)

    bus.publish(_EVENT)

    assert seen == [_EVENT]


def test_background_subscriber_runs_off_the_publishing_thread() -> None:
    bus = EventBus()
    threads: list[int] = []
    bus.subscribe(RiskBreached, lambda event: threads.append(threading.get_ident()))

    bus.publish(_EVENT)
    bus.close()

    assert threads and threads[0] != threading.get_ident()


def test_subscribers_only_see_their_event_type_and_object_sees_all() -> None:
    bus = EventBus()
    risk: list[object] = []
    everything: list[object] = []
    bus.subscribe(RiskBreached, risk.append, background=False)
    bus.subscribe(object, everything.append, background=False)
    sync = InstrumentSyncCompleted(broker="zerodha", count=1)

    bus.publish(_EVENT)
    bus.publish(sync)

    assert risk == [_EVENT]
    assert everything == [_EVENT, sync]


def test_event_bus_bounded_queue_rejects_or_blocks_at_cap() -> None:
    """At the cap, the next background handler runs inline in the publisher:
    nothing is dropped and the queue never grows past `max_pending`."""
    bus = EventBus(max_pending=1, workers=1)
    release = threading.Event()
    ran_on: list[int] = []

    def hold_slot(event: RiskBreached) -> None:
        release.wait(timeout=5)

    bus.subscribe(RiskBreached, hold_slot)
    bus.subscribe(
        InstrumentSyncCompleted, lambda event: ran_on.append(threading.get_ident())
    )

    bus.publish(_EVENT)  # takes the only slot and holds it until `release`
    bus.publish(InstrumentSyncCompleted(broker="zerodha", count=1))  # no slot left
    release.set()
    bus.close()

    assert ran_on == [threading.get_ident()]  # ran inline, in the publisher's thread


def test_failing_handler_is_logged_and_does_not_stop_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()
    seen: list[object] = []

    def broken(event: RiskBreached) -> None:
        raise RuntimeError("boom")

    bus.subscribe(RiskBreached, broken, background=False)
    bus.subscribe(RiskBreached, seen.append, background=False)

    with caplog.at_level(logging.ERROR):
        bus.publish(_EVENT)  # must not raise

    assert seen == [_EVENT]
    assert "boom" in caplog.text


def test_publish_after_close_runs_inline() -> None:
    bus = EventBus()
    seen: list[object] = []
    bus.subscribe(RiskBreached, seen.append)
    bus.close()

    bus.publish(_EVENT)

    assert seen == [_EVENT]
