from typing import Protocol


class NotificationPort(Protocol):
    def send(self, recipient: str, subject: str, message: str) -> None: ...
