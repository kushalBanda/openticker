"""Agent jobs as MCP and REST see them (ADR 29 in docs/adr): asking for a
review, setting when a strategy is reviewed without being asked, and reading
what jobs did. Only the daemon starts them."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from openticker.core.agents.jobs import (
    AgentJob,
    AgentJobEndReason,
    AgentJobKind,
    AgentJobStatus,
    AgentSettings,
    job_title,
)
from openticker.core.agents.reviews import ReviewSchedule, parse_every
from openticker.events.bus import EventPublisher
from openticker.events.types import AgentJobEnded
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage import agent_job_files
from openticker.storage.sqlite import agent_jobs_repo, strategies_repo
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.strategies_repo import StoredStrategy, write_transaction
from openticker.use_cases.strategies.define import UnknownStrategyError

MAX_AGENT_JOBS = 50  # per answer (ADR 8 in docs/adr)


class AgentJobBusyError(Exception):
    pass


class AgentJobCapError(Exception):
    pass


class UnknownAgentJobError(LookupError):
    pass


@dataclass(frozen=True)
class AgentJobLog:
    job: AgentJob
    text: str  # the end of what it printed
    truncated: bool  # older output left out


def start_review(
    strategy_id: str, settings: AgentSettings, triggered_by: str, now: datetime
) -> AgentJob:
    """A pending review job for openticker-serve to run. One job per strategy
    at a time, and at most the day's cap started."""
    with write_transaction() as session:
        if strategies_repo.find_strategy(strategy_id) is None:
            raise _unknown_strategy(strategy_id)
        open_job = agent_jobs_repo.open_job_of(session, strategy_id)
        if open_job is not None:
            raise AgentJobBusyError(
                f"a review of this strategy is already {open_job.status} (job {open_job.id}); "
                "get_agent_jobs shows it"
            )
        today = now.astimezone(EXCHANGE_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        if agent_jobs_repo.started_since(session, today) >= settings.jobs_per_day:
            raise AgentJobCapError(
                f"{settings.jobs_per_day} agent jobs have run today, the daily cap "
                "(OPENTICKER_AGENT_JOBS_PER_DAY); try again tomorrow"
            )
        return agent_jobs_repo.add_job(
            session, AgentJobKind.REVIEW, strategy_id, settings.harness, triggered_by, now
        )


def schedule_review(
    strategy_id: str,
    every: str | None,
    after_runs: int | None,
    drawdown: float | None,
    now: datetime,
) -> StoredStrategy:
    """Has openticker-serve review the strategy when any of the triggers is
    met (core/agents/reviews.py), replacing an earlier schedule. Counting
    starts now."""
    schedule = ReviewSchedule(
        set_at=now,
        every=parse_every(every) if every is not None else None,
        after_runs=after_runs,
        drawdown=drawdown,
    )
    with write_transaction() as session:
        stored = _strategy(session, strategy_id)
        strategies_repo.set_review_schedule(session, strategy_id, schedule)
    return strategies_repo.find_strategy(strategy_id) or stored


def unschedule_review(strategy_id: str) -> StoredStrategy:
    """Reviewed only when asked again. A review already waiting or running
    carries on."""
    with write_transaction() as session:
        stored = _strategy(session, strategy_id)
        strategies_repo.set_review_schedule(session, strategy_id, None)
    return strategies_repo.find_strategy(strategy_id) or stored


def strategy_names() -> dict[str, str]:
    """Every strategy's name by id: what a job's title names."""
    return {s.id: s.name for s in strategies_repo.list_strategies()}


def get_agent_jobs(limit: int, strategy_id: str | None = None) -> list[AgentJob]:
    return agent_jobs_repo.recent_jobs(min(limit, MAX_AGENT_JOBS), strategy_id)


def jobs_started_today(now: datetime) -> int:
    """Jobs started since the exchange-local midnight: what the day's cap counts."""
    today = now.astimezone(EXCHANGE_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    with Session(get_engine()) as session:
        return agent_jobs_repo.started_since(session, today)


def get_agent_job_log(job_id: str) -> AgentJobLog:
    job = agent_jobs_repo.find_job(job_id)
    if job is None:
        raise UnknownAgentJobError(f"no agent job {job_id!r}; get_agent_jobs lists them")
    text, truncated = agent_job_files.log_tail(job_id)
    return AgentJobLog(job, text, truncated)


def stop_agent_job(
    job_id: str, events: EventPublisher, triggered_by: str, now: datetime
) -> AgentJob:
    """A waiting job ends at once, never started. A running one is asked to
    stop: openticker-serve sends it SIGTERM and kills it if it's still there
    after the grace. An ended one is left as it is."""
    with write_transaction() as session:
        job = agent_jobs_repo.find_job(job_id)
        if job is None:
            raise UnknownAgentJobError(f"no agent job {job_id!r}; get_agent_jobs lists them")
        if job.status is AgentJobStatus.PENDING:
            ended = agent_jobs_repo.end_job(
                session,
                job_id,
                AgentJobEndReason.STOPPED,
                f"stopped by {triggered_by} before it started",
                now,
            )
        else:
            ended = None
            agent_jobs_repo.request_stop(
                session, job_id, AgentJobEndReason.STOPPED, f"stopped by {triggered_by}", now
            )
    if ended is not None:
        stored = strategies_repo.find_strategy(ended.strategy_id) if ended.strategy_id else None
        events.publish(
            AgentJobEnded(
                job_id=ended.id,
                kind=ended.kind,
                strategy_id=ended.strategy_id,
                subject=ended.subject,
                title=job_title(ended.kind, stored.name if stored else None, ended.subject),
                strategy_name=stored.name if stored else ended.strategy_id,
                reason=AgentJobEndReason.STOPPED,
                detail=ended.end_detail or "",
                summary=None,
                cost_usd=None,
            )
        )
    return agent_jobs_repo.find_job(job_id) or job


def _unknown_strategy(strategy_id: str) -> UnknownStrategyError:
    return UnknownStrategyError(
        f"no strategy with id {strategy_id!r}; list_strategies shows the ones that exist"
    )


def _strategy(session: Session, strategy_id: str) -> StoredStrategy:
    stored = strategies_repo.load_strategy(session, strategy_id)
    if stored is None:
        raise _unknown_strategy(strategy_id)
    return stored
