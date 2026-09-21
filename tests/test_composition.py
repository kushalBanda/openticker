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
        notification_channels({key: value for key, value in _SMTP.items() if key != "SMTP_PASSWORD"})


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
