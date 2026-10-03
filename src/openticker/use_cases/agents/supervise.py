"""The daemon's side of agent jobs (ADR 29 in docs/adr): asks for the
reviews that are due on their strategies' schedules, starts pending jobs
one at a time, holds each to its timeout, and records how it ended, with
the agent's answer and cost when the harness reports them. After a restart,
a job a previous daemon left running is stopped and ends `lost`: a
half-finished review is run again by asking for it again, not resumed.

Each job gets its own API key, scoped to what its kind may read, created as
it starts and revoked as it ends. The key reaches the agent only through
its environment and is stored only as a hash.
"""

import logging
import time as clock_time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from openticker.core.agents.jobs import (
    SCHEDULE_TRIGGER,
    AgentJob,
    AgentJobEndReason,
    AgentJobStatus,
    AgentSettings,
    capped,
    exit_reason,
    review_prompt,
)
from openticker.core.agents.reviews import review_due
from openticker.events.bus import EventPublisher
from openticker.events.types import AgentJobEnded, AgentJobStarted
from openticker.ports.agent_job_port import AgentLaunch, AgentProcesses
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage import agent_job_files
from openticker.storage.sqlite import agent_jobs_repo, strategies_repo
from openticker.storage.sqlite.api_keys_repo import DuplicateApiKeyNameError, revoke_api_key
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.agents.manage import AgentJobBusyError, AgentJobCapError, start_review
from openticker.use_cases.api_keys import agent_key_name, create_review_key, revoke_agent_keys
from openticker.use_cases.strategies.define import UnknownStrategyError
from openticker.use_cases.strategies.ledger import ledger_runs

log = logging.getLogger(__name__)

STOP_GRACE = timedelta(seconds=10)  # from SIGTERM to SIGKILL
KEPT_JOBS = 50  # jobs whose output is kept


@dataclass(frozen=True)
class AgentContext:
    processes: AgentProcesses
    events: EventPublisher
    settings: AgentSettings
    labs_dir: Path
    mcp_url: str  # openticker-serve's MCP endpoint


def recover_jobs(context: AgentContext, now: datetime) -> None:
    """Stops what a previous daemon left running, and revokes every job key."""
    for job in agent_jobs_repo.active_jobs():
        if job.pid is not None and context.processes.is_job(job.pid, job.id):
            context.processes.stop(job.pid, force=True)
        _end(context, job, AgentJobEndReason.LOST, "openticker-serve restarted while it ran", now)
    revoke_agent_keys(now)


def queue_due_reviews(context: AgentContext, now: datetime) -> list[AgentJob]:
    """A pending review for each strategy whose schedule is due. One that
    can't be queued stays due and is tried on a later pass: a review of it
    is already open, or the jobs started today and those waiting fill the
    day's cap. Counting the waiting ones keeps a scheduled review from being
    queued only to be refused when its turn comes."""
    queued = []
    for stored in strategies_repo.list_review_scheduled():
        assert stored.review_schedule is not None
        if _cap_taken(context.settings, now):
            break
        reason = review_due(
            stored.review_schedule,
            ledger_runs(stored.id),
            agent_jobs_repo.last_asked_at(stored.id),
            now,
        )
        if reason is None:
            continue
        try:
            job = start_review(stored.id, context.settings, SCHEDULE_TRIGGER + reason, now)
        except (AgentJobBusyError, AgentJobCapError, UnknownStrategyError):
            continue
        log.info("review of %s is due (%s): job %s", stored.name, reason, job.id)
        queued.append(job)
    return queued


def _cap_taken(settings: AgentSettings, now: datetime) -> bool:
    today = now.astimezone(EXCHANGE_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    with Session(get_engine()) as session:
        taken = agent_jobs_repo.started_since(session, today) + agent_jobs_repo.pending_count(
            session
        )
    return taken >= settings.jobs_per_day


def start_next_job(context: AgentContext, now: datetime) -> None:
    """Starts the oldest pending job, unless one is running."""
    with write_transaction() as session:
        if agent_jobs_repo.active_jobs(session):
            return
        job = agent_jobs_repo.next_pending(session)
        if job is None:
            return
        today = now.astimezone(EXCHANGE_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        started_today = agent_jobs_repo.started_since(session, today)
        stored = strategies_repo.find_strategy(job.strategy_id)
        refusal = None
        if stored is None:
            refusal = "its strategy was deleted"
        elif started_today >= context.settings.jobs_per_day:
            refusal = f"{context.settings.jobs_per_day} jobs already ran today, the daily cap"
        if refusal is None:
            agent_jobs_repo.mark_started(session, job.id, now)
    if refusal is not None or stored is None:
        _end(context, job, AgentJobEndReason.REFUSED, refusal or "", now)
        return
    local = now.astimezone(EXCHANGE_TIMEZONE)
    agent_job_files.append_log(
        job.id,
        f"=== job {job.id} ({job.kind} of {stored.name}) started {local:%Y-%m-%d %H:%M:%S %Z} "
        f"with {job.harness}, asked by {job.trigger} ===",
    )
    try:
        key = create_review_key(job.strategy_id, job.id, now)
        pid = context.processes.start(
            AgentLaunch(
                job_id=job.id,
                harness=job.harness,
                prompt=review_prompt(stored.name, stored.id, job.id, job.trigger),
                labs_dir=context.labs_dir,
                log_path=agent_job_files.log_path(job.id),
                result_path=agent_job_files.result_path(job.id),
                api_key=key,
                mcp_url=context.mcp_url,
                max_budget_usd=context.settings.max_budget_usd,
            )
        )
    except (DuplicateApiKeyNameError, OSError) as exc:
        _end(context, job, AgentJobEndReason.START_FAILED, f"could not start: {exc}", now)
        return
    with write_transaction() as session:
        agent_jobs_repo.mark_running(session, job.id, pid, now)
    agent_job_files.prune({kept.id for kept in agent_jobs_repo.recent_jobs(KEPT_JOBS)})
    log.info("agent job %s (%s of %s) started, pid %d", job.id, job.kind, stored.name, pid)
    context.events.publish(
        AgentJobStarted(job.id, job.kind, job.strategy_id, job.harness, job.trigger)
    )


def watch_jobs(context: AgentContext, now: datetime) -> None:
    """Records a job that ended, kills one that outstayed a stop, and stops
    one past its timeout."""
    for job in agent_jobs_repo.active_jobs():
        if job.pid is None:
            continue
        exited = context.processes.poll(job.pid)
        if exited is not None:
            _finish(context, job, exited.returncode, now)
            continue
        if job.status is AgentJobStatus.STOPPING:
            # Asked from another process too (stop_agent_job), which can't
            # signal it: SIGTERM each pass until the grace, then SIGKILL.
            late = now - (job.stop_requested_at or now) >= STOP_GRACE
            context.processes.stop(job.pid, force=late)
            continue
        if job.started_at is not None and now - job.started_at >= context.settings.timeout:
            minutes = int(context.settings.timeout.total_seconds() // 60)
            with write_transaction() as session:
                agent_jobs_repo.request_stop(
                    session,
                    job.id,
                    AgentJobEndReason.TIMEOUT,
                    f"still running after {minutes} minutes",
                    now,
                )
            context.processes.stop(job.pid, force=False)


def stop_all_jobs(
    context: AgentContext,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None] = clock_time.sleep,
) -> None:
    """At shutdown: asks every job to stop, kills what's left after the
    grace, and records each as ended `daemon_stopped`."""
    jobs = [job for job in agent_jobs_repo.active_jobs() if job.pid is not None]
    for job in jobs:
        assert job.pid is not None
        context.processes.stop(job.pid, force=False)
    deadline = clock() + STOP_GRACE
    waiting = {job.id: job for job in jobs}
    while waiting and clock() < deadline:
        for job in list(waiting.values()):
            assert job.pid is not None
            if context.processes.poll(job.pid) is not None:
                del waiting[job.id]
        if waiting:
            sleep(0.1)
    for job in waiting.values():
        assert job.pid is not None
        context.processes.stop(job.pid, force=True)
    for job in jobs:
        _end(context, job, AgentJobEndReason.DAEMON_STOPPED, "openticker-serve shut down", clock())


def _finish(context: AgentContext, job: AgentJob, returncode: int | None, now: datetime) -> None:
    """A job whose process ended: the reason it was asked to stop wins over
    its exit status, which the detail still gives."""
    current = agent_jobs_repo.find_job(job.id) or job
    reason, detail = exit_reason(returncode)
    if current.end_reason is not None:
        reason, detail = current.end_reason, f"{current.end_detail}; {detail}"
    outcome = context.processes.outcome(job.harness, agent_job_files.result_path(job.id))
    _end(
        context, current, reason, detail, now, returncode, capped(outcome.summary), outcome.cost_usd
    )


def _end(
    context: AgentContext,
    job: AgentJob,
    reason: AgentJobEndReason,
    detail: str,
    now: datetime,
    exit_code: int | None = None,
    summary: str | None = None,
    cost_usd: float | None = None,
) -> None:
    with write_transaction() as session:
        ended = agent_jobs_repo.end_job(
            session, job.id, reason, detail, now, exit_code, summary, cost_usd
        )
    revoke_api_key(agent_key_name(job.id), now)
    if ended is None:
        return
    agent_job_files.append_log(job.id, f"=== job {job.id} ended: {reason}, {detail} ===")
    log.info("agent job %s ended: %s, %s", job.id, reason, detail)
    stored = strategies_repo.find_strategy(job.strategy_id)
    context.events.publish(
        AgentJobEnded(
            job_id=job.id,
            kind=job.kind,
            strategy_id=job.strategy_id,
            strategy_name=stored.name if stored else job.strategy_id,
            reason=reason,
            detail=detail,
            summary=summary,
            cost_usd=cost_usd,
        )
    )
