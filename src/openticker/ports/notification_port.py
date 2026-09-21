from typing import Protocol


class NotificationPort(Protocol):
    """A channel that delivers a short message to the user. Where it goes (a
    Slack channel, an email address) is the adapter's configuration."""

    def send(self, subject: str, message: str) -> None: ...
