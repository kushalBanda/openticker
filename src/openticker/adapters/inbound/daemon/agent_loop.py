"""The daemon's agent jobs (ADR 29 in docs/adr): every second, records jobs
that ended and stops one past its timeout, then starts the oldest pending
job if none is running, and the oldest waiting chat turns (ADR 40). Every
minute, it first asks for the day's debrief when it's due after the close,
and wakes the desk manager when it's due (ADR 41). Its first pass stops
what a previous daemon left running; when the daemon stops, it stops every job. Each pass reads the web
app's Settings afresh (ADR 40), so a change applies without a restart.

`step()` does one pass and is what the tests drive; `run()` repeats it and
keeps going through errors, logging each distinct one once.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from openticker.use_cases.agents.manager import queue_due_manager_wake
from openticker.use_cases.agents.settings import resolved_settings
from openticker.use_cases.agents.supervise import (
    AgentContext,
    queue_due_debrief,
    recover_jobs,
    start_next_chat_turn,
    start_next_job,
    stop_all_jobs,
    watch_jobs,
)

log = logging.getLogger(__name__)

# How often the debrief and the desk manager are asked whether they're due:
# each check reads the audit log and the day's figures, and no wake needs
# finer timing.
DUE_CHECK_EVERY = timedelta(minutes=1)


class AgentLoop:
    def __init__(
        self,
        context: AgentContext,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._context = context
        self._clock = clock
        self._recovered = False
        self._next_due_check: datetime | None = None
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
        context = replace(self._context, settings=resolved_settings(self._context.settings))
        if not self._recovered:
            recover_jobs(context, now)
            self._recovered = True
        watch_jobs(context, now)
        if self._next_due_check is None or now >= self._next_due_check:
            self._next_due_check = now + DUE_CHECK_EVERY
            queue_due_debrief(context, now)
            queue_due_manager_wake(context, now)
        start_next_job(context, now)
        start_next_chat_turn(context, now)
