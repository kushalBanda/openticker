"""The daemon's agent jobs (ADR 29 in docs/adr): every second, records jobs
that ended and stops one past its timeout, then starts the oldest pending
job if none is running. Every minute, it first asks for the reviews that
are due on their strategies' schedules. Its first pass stops what a previous daemon left
running; when the daemon stops, it stops every job.

`step()` does one pass and is what the tests drive; `run()` repeats it and
keeps going through errors, logging each distinct one once.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from openticker.use_cases.agents.supervise import (
    AgentContext,
    queue_due_reviews,
    recover_jobs,
    start_next_job,
    stop_all_jobs,
    watch_jobs,
)

log = logging.getLogger(__name__)

# How often schedules are checked: each check reads every scheduled
# strategy's ledger, and no trigger needs finer timing.
REVIEW_CHECK_EVERY = timedelta(minutes=1)


class AgentLoop:
    def __init__(
        self,
        context: AgentContext,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._context = context
        self._clock = clock
        self._recovered = False
        self._next_review_check: datetime | None = None
        self._last_error: str | None = None

    def run(self, stop: threading.Event) -> None:
        try:
            while not stop.is_set():
                try:
                    self.step()
                    self._last_error = None
                except Exception as exc:  # a bug here must not end the daemon's agent jobs
                    if str(exc) != self._last_error:
                        log.exception("agent job pass failed")
                        self._last_error = str(exc)
                stop.wait(1.0)
        finally:
            stop_all_jobs(self._context, self._clock)

    def step(self) -> None:
        now = self._clock()
        if not self._recovered:
            recover_jobs(self._context, now)
            self._recovered = True
        watch_jobs(self._context, now)
        if self._next_review_check is None or now >= self._next_review_check:
            self._next_review_check = now + REVIEW_CHECK_EVERY
            queue_due_reviews(self._context, now)
        start_next_job(self._context, now)
