from email.message import EmailMessage
from types import TracebackType
from typing import Any, ClassVar, Self

import httpx
import pytest

from openticker.adapters.notifications.email import EmailAdapter, SmtpSettings
from openticker.adapters.notifications.slack import NotificationError, SlackAdapter

_SETTINGS = SmtpSettings(
    host="smtp.example.com",
    port=587,
    username="bot@example.com",
    password="pw",
    sender="bot@example.com",
    recipient="me@example.com",
)


def test_slack_adapter_posts_to_webhook_url(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, str], timeout: float) -> httpx.Response:
        posted.update(url=url, json=json)
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(httpx, "post", fake_post)

    SlackAdapter("https://hooks.slack.com/services/T/B/secret").send("Subject", "Body")

    assert posted == {
        "url": "https://hooks.slack.com/services/T/B/secret",
        "json": {"text": "*Subject*\nBody"},
    }


def test_slack_error_never_leaks_the_webhook_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: httpx.Response(404))

    with pytest.raises(NotificationError) as raised:
        SlackAdapter("https://hooks.slack.com/services/T/B/secret").send("s", "m")

    assert "secret" not in str(raised.value)


class _FakeSmtp:
    instances: ClassVar[list["_FakeSmtp"]] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.address = (host, port)
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        _FakeSmtp.instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        pass

    def starttls(self) -> None:
        self.calls.append("starttls")

    def login(self, username: str, password: str) -> None:
        self.calls.append(f"login:{username}")

    def send_message(self, message: EmailMessage) -> None:
        self.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSmtp]:
    _FakeSmtp.instances = []
    monkeypatch.setattr("smtplib.SMTP", _FakeSmtp)
    monkeypatch.setattr("smtplib.SMTP_SSL", _FakeSmtp)
    return _FakeSmtp


def test_email_adapter_upgrades_with_starttls_and_sends(fake_smtp: type[_FakeSmtp]) -> None:
    EmailAdapter(_SETTINGS).send("Order placed", "Details")

    [smtp] = fake_smtp.instances
    assert smtp.address == ("smtp.example.com", 587)
    assert smtp.calls == ["starttls", "login:bot@example.com"]
    [message] = smtp.sent
    assert message["To"] == "me@example.com"
    assert message["Subject"] == "[OpenTicker] Order placed"


def test_email_adapter_uses_implicit_tls_on_465(fake_smtp: type[_FakeSmtp]) -> None:
    EmailAdapter(SmtpSettings(**{**_SETTINGS.__dict__, "port": 465})).send("s", "m")

    [smtp] = fake_smtp.instances
    assert smtp.calls == ["login:bot@example.com"]  # no STARTTLS on an already-TLS socket
