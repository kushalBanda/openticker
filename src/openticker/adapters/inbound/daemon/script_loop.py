"""The daemon's script supervisor (ADR 25 in docs/adr): every second, carries
out start and stop commands, records the runs that ended and holds the rest
to their limits and stop times, then starts scheduled scripts whose window
is open. Its first pass takes back the scripts a previous daemon left
running; when the daemon stops, it stops every script.

`step()` does one pass and is what the tests drive; `run()` repeats it and
keeps going through errors, logging each distinct one once.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from openticker.core.calendar.models import MarketCalendar
from openticker.core.scripts.models import ScriptLimits
from openticker.events.bus import EventPublisher
from openticker.ports.script_process_port import ScriptProcesses
from openticker.use_cases.scripts.supervise import (
    SupervisorContext,
    process_script_commands,
    recover_scripts,
    start_scheduled_scripts,
    stop_all_scripts,
    watch_scripts,
)

log = logging.getLogger(__name__)

CALENDAR_RELOAD = timedelta(minutes=10)


class ScriptLoop:
    def __init__(
        self,
        processes: ScriptProcesses,
        events: EventPublisher,
        calendar: Callable[[], MarketCalendar],
        limits: ScriptLimits,
        base_url: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._processes = processes
        self._events = events
        self._load_calendar = calendar
        self._limits = limits
        self._base_url = base_url
        self._clock = clock
        self._calendar: MarketCalendar | None = None
        self._calendar_loaded_at = datetime.min.replace(tzinfo=UTC)
        self._recovered = False
        self._last_error: str | None = None

    def run(self, stop: threading.Event) -> None:
        try:
            while not stop.is_set():
                try:
                    self.step()
                    self._last_error = None
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    if message != self._last_error:
                        log.exception("script supervisor pass failed")
                        self._last_error = message
                stop.wait(1.0)
        finally:
            self.shutdown()

    def step(self) -> None:
        now = self._clock()
        context = self._context(now)
        if not self._recovered:
            if count := recover_scripts(context, now):
                log.info("watching %d script(s) left running by the last run", count)
            self._recovered = True
        process_script_commands(context, now)
        watch_scripts(context, now)
        start_scheduled_scripts(context, now)

    def shutdown(self) -> None:
        """Stops every script, before the daemon exits."""
        try:
            stop_all_scripts(self._context(self._clock()), self._clock)
        except Exception:
            log.exception("stopping scripts at shutdown failed")

    def _context(self, now: datetime) -> SupervisorContext:
        if self._calendar is None or now - self._calendar_loaded_at >= CALENDAR_RELOAD:
            self._calendar = self._load_calendar()
            self._calendar_loaded_at = now
        return SupervisorContext(
            processes=self._processes,
            events=self._events,
            calendar=self._calendar,
            limits=self._limits,
            base_url=self._base_url,
        )
