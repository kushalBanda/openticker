import pytest

from openticker.adapters.notifications.email import EmailAdapter
from openticker.adapters.notifications.slack import SlackAdapter
from openticker.composition import (
    NotificationConfigError,
    build_event_bus,
    notification_channels,
)
from openticker.events.types import InstrumentSyncCompleted
from openticker.storage.sqlite.audit_repo import list_audit

_SMTP = {
    "SMTP_HOST": "smtp.example.com",
    "SMTP_USERNAME": "bot@example.com",
    "SMTP_PASSWORD": "pw",
    "NOTIFY_EMAIL_FROM": "alerts@example.com",
    "NOTIFY_EMAIL_TO": "me@example.com",
}


def test_no_notification_settings_means_no_channels() -> None:
    assert notification_channels({}) == []


def test_each_configured_channel_is_built() -> None:
    channels = notification_channels({"SLACK_WEBHOOK_URL": "https://hooks.slack.com/x", **_SMTP})

    assert [type(channel) for channel in channels] == [SlackAdapter, EmailAdapter]


def test_partial_smtp_settings_fail_loudly() -> None:
    with pytest.raises(NotificationConfigError, match="SMTP_PASSWORD"):
        notification_channels(
            {key: value for key, value in _SMTP.items() if key != "SMTP_PASSWORD"}
        )


def test_built_bus_audits_every_event_synchronously() -> None:
    bus = build_event_bus({})

    bus.publish(InstrumentSyncCompleted(broker="zerodha", count=3))

    [entry] = list_audit(10)  # already written: the audit subscriber is inline
    assert entry.event_type == "InstrumentSyncCompleted"
    bus.close()


def test_smtp_username_is_never_assumed_to_be_the_sender() -> None:
    resend_style = {**_SMTP, "SMTP_USERNAME": "resend"}
    del resend_style["NOTIFY_EMAIL_FROM"]

    with pytest.raises(NotificationConfigError, match="NOTIFY_EMAIL_FROM"):
        notification_channels(resend_style)


def test_sandbox_settings_read_positive_numbers_and_reject_the_rest() -> None:
    from openticker.composition import SandboxConfigError, capital_cap, sandbox_settings

    assert sandbox_settings({}).starting_capital == 10_000_000.0
    assert sandbox_settings({"SANDBOX_STARTING_CAPITAL": "5,00,000"}).starting_capital == 500_000.0
    assert capital_cap({}) is None
    assert capital_cap({"OPENTICKER_CAPITAL_CAP": "200000"}) == 200_000.0
    for bad in ("-1", "lots", "nan"):
        with pytest.raises(SandboxConfigError, match="OPENTICKER_CAPITAL_CAP"):
            capital_cap({"OPENTICKER_CAPITAL_CAP": bad})


def test_watch_list_reads_exchange_symbol_pairs() -> None:
    from openticker.composition import WatchConfigError, watch_list
    from openticker.ports.models import Exchange

    assert watch_list({}) == []
    assert watch_list({"OPENTICKER_WATCH": "NSE:NIFTY 50, NFO:NIFTY29SEP26FUT,"}) == [
        ("NIFTY 50", Exchange.NSE),
        ("NIFTY29SEP26FUT", Exchange.NFO),
    ]
    for bad in ("NIFTY 50", "NYSE:IBM", "NSE:"):
        with pytest.raises(WatchConfigError, match="EXCHANGE:SYMBOL"):
            watch_list({"OPENTICKER_WATCH": bad})


def test_price_timeouts_come_from_the_environment() -> None:
    from datetime import timedelta

    from openticker.composition import SandboxConfigError, price_timeouts
    from openticker.core.strategies.prices import PriceTimeouts

    assert price_timeouts({}) == PriceTimeouts()
    assert price_timeouts(
        {"STRATEGY_TICK_FALLBACK_SECONDS": "5", "STRATEGY_TICK_STALE_SECONDS": "30"}
    ) == PriceTimeouts(timedelta(seconds=5), timedelta(seconds=30))
    with pytest.raises(SandboxConfigError, match="less than"):
        price_timeouts({"STRATEGY_TICK_FALLBACK_SECONDS": "90"})
    with pytest.raises(SandboxConfigError, match="positive"):
        price_timeouts({"STRATEGY_TICK_STALE_SECONDS": "-1"})


def test_script_limits_are_whole_numbers_with_defaults() -> None:
    from openticker.composition import ScriptConfigError, script_limits
    from openticker.core.scripts.models import ScriptLimits

    assert script_limits({}) == ScriptLimits(1024, 3600)
    assert script_limits({"SCRIPT_MEMORY_LIMIT_MB": "512", "SCRIPT_CPU_SECONDS": " 60 "}) == (
        ScriptLimits(512, 60)
    )
    with pytest.raises(ScriptConfigError, match="SCRIPT_MEMORY_LIMIT_MB must be a whole number"):
        script_limits({"SCRIPT_MEMORY_LIMIT_MB": "1.5"})
    with pytest.raises(ScriptConfigError, match="at least 64 MB"):
        script_limits({"SCRIPT_MEMORY_LIMIT_MB": "10"})
    with pytest.raises(ScriptConfigError, match="at least 1 second"):
        script_limits({"SCRIPT_CPU_SECONDS": "0"})
