"""The daemon's side of agent jobs (ADR 29 in docs/adr): asks for the
reviews that are due on their strategies' schedules and the day's debrief
when it is due after the close, starts pending jobs
one at a time, holds each to its timeout, and records how it ended, with
the agent's answer and cost when the harness reports them. After a restart,
a job a previous daemon left running is stopped and ends `lost`: a
half-finished review is run again by asking for it again, not resumed.

Chat turns (ADR 40) run in a lane of their own: a few at once, beside the
background job, and not counted against the day's cap, since the user is
there asking. Each resumes its thread's conversation; the first stores the
harness's session on the thread.

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

from openticker.core.agents.choices import (
    FolderKind,
    RunChoice,
    folder_kind,
    job_kind_folder,
    look_kind,
    run_choice,
)
from openticker.core.agents.debriefs import DebriefOutcome
from openticker.core.agents.jobs import (
    AgentJob,
    AgentJobEndReason,
    AgentJobKind,
    AgentJobStatus,
    AgentSettings,
    Harness,
    capped,
    debrief_prompt,
    exit_reason,
    job_title,
    review_prompt,
    start_failure,
)
from openticker.core.agents.threads import (
    Access,
    AgentThread,
    chat_prompt_context,
    folder_context,
)
from openticker.core.agents.transcript import Usage, own_usage, session_gone
from openticker.events.bus import EventPublisher
from openticker.events.types import AgentJobEnded, AgentJobStarted
from openticker.ports.agent_job_port import AgentLaunch, AgentOutcome, AgentProcesses
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage import agent_job_files
from openticker.storage.sqlite import agent_jobs_repo, agent_threads_repo, strategies_repo
from openticker.storage.sqlite.api_keys_repo import DuplicateApiKeyNameError, revoke_api_key
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.agents.threads import subject_name
from openticker.use_cases.api_keys import (
    agent_key_name,
    create_chat_key,
    create_debrief_key,
    create_review_key,
    revoke_agent_keys,
)
from openticker.use_cases.brain.debrief import DEBRIEF_TRIGGER, debrief_outcome, write_quiet_day

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


def queue_due_debrief(context: AgentContext, now: datetime) -> AgentJob | None:
    """Today's debrief, when it's due (core/agents/debriefs.py): a pending
    job, or on a quiet day a one-line note the server writes itself. Waits
    while the day's cap is taken."""
    outcome, today = debrief_outcome(now)
    if outcome is DebriefOutcome.QUIET:
        write_quiet_day(today, context.events, now)
        log.info("debrief of %s: a quiet day, noted without a job", today)
        return None
    if outcome is not DebriefOutcome.DUE or _cap_taken(context.settings, now):
        return None
    with write_transaction() as session:
        if agent_jobs_repo.debrief_for(session, today) is not None:
            return None
        choice = run_choice(context.settings, FolderKind.DEBRIEFS)
        job = agent_jobs_repo.add_job(
            session,
            AgentJobKind.DEBRIEF,
            None,
            choice.harness or context.settings.harness,
            DEBRIEF_TRIGGER,
            now,
            subject=today,
            model=choice.model,
            effort=choice.effort or None,
        )
        job = agent_threads_repo.open_job_thread(
            session, job, job_title(job.kind, None, today), now
        )
    log.info("debrief of %s is due: job %s", today, job.id)
    return job


def _cap_taken(settings: AgentSettings, now: datetime) -> bool:
    today = now.astimezone(EXCHANGE_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    with Session(get_engine()) as session:
        taken = agent_jobs_repo.started_since(session, today) + agent_jobs_repo.pending_count(
            session
        )
    return taken >= settings.jobs_per_day


def start_next_job(context: AgentContext, now: datetime) -> None:
    """Starts the oldest pending background job, unless one is running."""
    with write_transaction() as session:
        if agent_jobs_repo.active_background(session):
            return
        job = agent_jobs_repo.next_pending(session)
        if job is None:
            return
        today = now.astimezone(EXCHANGE_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        started_today = agent_jobs_repo.started_since(session, today)
        stored = strategies_repo.find_strategy(job.strategy_id) if job.strategy_id else None
        refusal = None
        if job.kind is AgentJobKind.REVIEW and stored is None:
            refusal = "its strategy was deleted"
        elif job.kind is AgentJobKind.DEBRIEF and job.subject is None:
            refusal = "it names no trading day"
        elif started_today >= context.settings.jobs_per_day:
            refusal = f"{context.settings.jobs_per_day} jobs already ran today, the daily cap"
        if refusal is None:
            agent_jobs_repo.mark_started(session, job.id, now)
    if refusal is not None:
        _end(context, job, AgentJobEndReason.REFUSED, refusal, now)
        return
    title = job_title(job.kind, stored.name if stored else None, job.subject)
    local = now.astimezone(EXCHANGE_TIMEZONE)
    agent_job_files.append_log(
        job.id,
        f"=== job {job.id} ({title}) started {local:%Y-%m-%d %H:%M:%S %Z} "
        f"with {job.harness}, asked by {job.trigger} ===",
    )
    try:
        if job.kind is AgentJobKind.DEBRIEF:
            assert job.subject is not None
            key = create_debrief_key(job.subject, job.id, now)
            prompt = debrief_prompt(job.subject, job.id, job.trigger)
            agent, writes_notes = "debrief", False
        else:
            assert stored is not None
            key = create_review_key(stored.id, job.id, now)
            prompt = review_prompt(stored.name, stored.id, job.id)
            agent, writes_notes = "reviewer", True
        pid = context.processes.start(
            AgentLaunch(
                job_id=job.id,
                harness=job.harness,
                prompt=prompt,
                labs_dir=context.labs_dir,
                log_path=agent_job_files.log_path(job.id),
                events_path=agent_job_files.events_path(job.id),
                result_path=agent_job_files.result_path(job.id),
                api_key=key,
                mcp_url=context.mcp_url,
                max_budget_usd=_choice_of(context, job).max_budget_usd,
                agent=agent,
                writes_notes=writes_notes,
                model=job.model,
                effort=job.effort,
            )
        )
    except (DuplicateApiKeyNameError, OSError) as exc:
        _end(context, job, AgentJobEndReason.START_FAILED, start_failure(job.harness, exc), now)
        return
    _running(context, job, pid, title, now)


def start_next_chat_turn(context: AgentContext, now: datetime) -> None:
    """Starts the oldest waiting chat turn while fewer than the chat lane's
    limit run."""
    with write_transaction() as session:
        running = agent_jobs_repo.active_chat_turns(session)
        if len(running) >= context.settings.chat_turns_at_once:
            return
        job = agent_jobs_repo.next_pending_chat(session)
        if job is None:
            return
        thread = agent_threads_repo.find_thread(job.thread_id, session) if job.thread_id else None
        refusal = None
        if thread is None or thread.deleted_at is not None:
            refusal = "its chat was deleted"
        elif thread.session_id is None and _follows_a_turn(session, job):
            # It waited behind a turn that left no conversation to resume.
            refusal = "the chat can't be continued: its conversation is gone. Start a new chat"
        if refusal is None:
            agent_jobs_repo.mark_started(session, job.id, now)
    if refusal is not None or thread is None:
        _end(context, job, AgentJobEndReason.REFUSED, refusal or "", now)
        return
    local = now.astimezone(EXCHANGE_TIMEZONE)
    agent_job_files.append_log(
        job.id,
        f"=== job {job.id} (chat {thread.id}) started {local:%Y-%m-%d %H:%M:%S %Z} "
        f"with {job.harness}, asked by {job.trigger} ===",
    )
    name = subject_name(thread)
    try:
        key = create_chat_key(thread.id, job.id, now, read_only=thread.access is Access.READ)
        pid = context.processes.start(
            AgentLaunch(
                job_id=job.id,
                harness=job.harness,
                prompt=job.prompt or "",
                labs_dir=context.labs_dir,
                log_path=agent_job_files.log_path(job.id),
                events_path=agent_job_files.events_path(job.id),
                result_path=agent_job_files.result_path(job.id),
                api_key=key,
                mcp_url=context.mcp_url,
                max_budget_usd=_choice_of(context, job, thread).max_budget_usd,
                agent=None,
                writes_notes=True,
                model=job.model,
                effort=job.effort,
                resume_session=thread.session_id,
                context=chat_prompt_context(
                    folder_context(thread.folder, thread.subject, name), job.id, thread.access
                ),
            )
        )
    except (DuplicateApiKeyNameError, OSError) as exc:
        _end(context, job, AgentJobEndReason.START_FAILED, start_failure(job.harness, exc), now)
        return
    _running(context, job, pid, job_title(job.kind, None, None), now)


def _follows_a_turn(session: Session, job: AgentJob) -> bool:
    turns = agent_jobs_repo.turns_of(job.thread_id or "", session)
    return bool(turns) and turns[0].id != job.id


def _choice_of(
    context: AgentContext, job: AgentJob, thread: AgentThread | None = None
) -> RunChoice:
    """The folder default a job runs under: its kind's, or its chat's folder's."""
    kind = job_kind_folder(job.kind)
    if kind is None:
        if thread is None and job.thread_id is not None:
            thread = agent_threads_repo.find_thread(job.thread_id)
        kind = folder_kind(thread.folder) if thread is not None else FolderKind.GENERAL
        if kind is FolderKind.MANAGER:
            kind = look_kind(job.trigger)  # a check-in's cap and time limit (ADR 42)
    return run_choice(context.settings, kind)


def _running(context: AgentContext, job: AgentJob, pid: int, title: str, now: datetime) -> None:
    with write_transaction() as session:
        agent_jobs_repo.mark_running(session, job.id, pid, now)
    kept = {kept.id for kept in agent_jobs_repo.recent_jobs(KEPT_JOBS)}
    agent_job_files.prune(
        kept | agent_jobs_repo.thread_job_ids(agent_threads_repo.live_thread_ids())
    )
    log.info("agent job %s (%s) started, pid %d", job.id, title, pid)
    context.events.publish(
        AgentJobStarted(
            job.id, job.kind, job.strategy_id, job.subject, title, job.harness, job.trigger
        )
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
        timeout = _choice_of(context, job).timeout or context.settings.timeout
        if job.started_at is not None and now - job.started_at >= timeout:
            minutes = int(timeout.total_seconds() // 60)
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
    outcome = context.processes.outcome(
        job.harness, agent_job_files.events_path(job.id), agent_job_files.result_path(job.id)
    )
    with write_transaction() as session:
        own = _own_usage(session, job, outcome)
        agent_jobs_repo.mark_outcome(session, job.id, outcome, own)
        thread = agent_threads_repo.find_thread(job.thread_id, session) if job.thread_id else None
        if thread is not None:
            if session_gone(outcome.error):
                # Nothing left to resume: the chat can only be started afresh.
                agent_threads_repo.set_session(session, thread.id, None)
                detail = f"its conversation can't be resumed; {detail}"
            elif thread.session_id is None and outcome.session_id is not None:
                agent_threads_repo.set_session(session, thread.id, outcome.session_id)
            agent_threads_repo.touch(session, thread.id, now)
    _end(
        context,
        current,
        reason,
        detail,
        now,
        returncode,
        capped(outcome.summary),
        own.cost_usd,
        outcome.model_used,
    )


def _own_usage(session: Session, job: AgentJob, outcome: AgentOutcome) -> Usage:
    """What this turn spent (ADR 42): Claude Code reports a resumed session's
    running total, so the previous turn's is taken off; Codex reports a run's
    own."""
    reported = Usage(outcome.cost_usd, outcome.input_tokens, outcome.output_tokens)
    if job.harness is not Harness.CLAUDE or job.thread_id is None or outcome.session_id is None:
        return reported
    before = agent_jobs_repo.previous_in_session(session, job.thread_id, outcome.session_id, job.id)
    return own_usage(reported, before)


def _end(
    context: AgentContext,
    job: AgentJob,
    reason: AgentJobEndReason,
    detail: str,
    now: datetime,
    exit_code: int | None = None,
    summary: str | None = None,
    cost_usd: float | None = None,
    model_used: str | None = None,
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
    stored = strategies_repo.find_strategy(job.strategy_id) if job.strategy_id else None
    thread = agent_threads_repo.find_thread(job.thread_id) if job.thread_id else None
    title = job_title(job.kind, stored.name if stored else None, job.subject)
    context.events.publish(
        AgentJobEnded(
            job_id=job.id,
            kind=job.kind,
            strategy_id=job.strategy_id,
            subject=job.subject,
            title=thread.title if thread and job.kind is AgentJobKind.CHAT else title,
            strategy_name=stored.name if stored else job.strategy_id,
            reason=reason,
            detail=detail,
            summary=summary,
            cost_usd=cost_usd,
            model_used=model_used,
            thread_id=job.thread_id,
            trigger=job.trigger,
        )
    )
