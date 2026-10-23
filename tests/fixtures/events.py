"""An event publisher for tests that keeps what was published."""

from datetime import UTC, datetime

# When a test's own setup changes something, if the time doesn't matter to it.
SET_UP_AT = datetime(2026, 9, 1, 3, 30, tzinfo=UTC)


class Recorded:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)
