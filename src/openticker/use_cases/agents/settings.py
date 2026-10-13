"""How the user's coding agent runs, as the web app's Settings set it (ADR 40
in docs/adr): a default for each folder kind, the harness every folder
uses, and the background runs a day. What Settings leave unset comes from
the server's environment (composition.agent_settings). Everything that
starts or holds a run reads `resolved_settings()` when it does, so a change
applies from the next run without a restart."""

from dataclasses import dataclass, replace
from datetime import datetime

from openticker.core.agents.choices import (
    MAX_RUNS_PER_DAY,
    FolderKind,
    RunChoice,
    check_choice,
    env_choice,
    resolved_choices,
    stored_choice,
)
from openticker.core.agents.jobs import AgentJobError, AgentSettings, Harness, harness_name
from openticker.events.bus import EventPublisher
from openticker.events.types import AgentSettingsChanged
from openticker.storage.sqlite import agent_settings_repo
from openticker.storage.sqlite.strategies_repo import write_transaction

FOLDER_NAMES = {
    FolderKind.GENERAL: "General",
    FolderKind.STRATEGIES: "Strategies",
    FolderKind.SCRIPTS: "Scripts",
    FolderKind.REVIEWS: "Reviews",
    FolderKind.DEBRIEFS: "Debriefs",
}


class AgentSettingsError(ValueError):
    """A choice the harness doesn't take, or a count out of range."""


@dataclass(frozen=True)
class FolderSettings:
    kind: FolderKind
    stored: RunChoice  # what Settings set
    env: RunChoice  # what OPENTICKER_AGENT_* gives
    resolved: RunChoice  # what a run uses with no override


@dataclass(frozen=True)
class AgentSettingsView:
    harness: Harness | None  # what Settings picked for every folder
    harness_env: Harness
    runs_per_day: int | None
    runs_per_day_env: int
    folders: list[FolderSettings]


def resolved_settings(env_settings: AgentSettings) -> AgentSettings:
    """The environment's settings with what Settings set on top."""
    stored = agent_settings_repo.stored_settings()
    return replace(
        env_settings,
        harness=stored.harness or env_settings.harness,
        jobs_per_day=stored.runs_per_day or env_settings.jobs_per_day,
        choices=resolved_choices(stored, env_settings),
    )


def read_settings(env_settings: AgentSettings) -> AgentSettingsView:
    stored = agent_settings_repo.stored_settings()
    resolved = resolved_choices(stored, env_settings)
    env = env_choice(env_settings)
    return AgentSettingsView(
        harness=stored.harness,
        harness_env=env_settings.harness,
        runs_per_day=stored.runs_per_day,
        runs_per_day_env=env_settings.jobs_per_day,
        folders=[
            FolderSettings(
                kind, stored_choice(stored, kind, env_settings.harness), env, resolved[kind]
            )
            for kind in FolderKind
        ],
    )


def set_folder_choice(
    kind: FolderKind,
    choice: RunChoice,
    env_settings: AgentSettings,
    triggered_by: str,
    events: EventPublisher,
    now: datetime,
) -> FolderSettings:
    """Replaces a folder kind's default; a field left None comes from the
    harness Settings picked, then the environment."""
    stored = agent_settings_repo.stored_settings()
    harness = choice.harness or stored.harness or env_settings.harness
    try:
        check_choice(choice, harness)
    except AgentJobError as exc:
        raise AgentSettingsError(str(exc)) from None
    with write_transaction() as session:
        agent_settings_repo.save_choice(session, kind, choice, harness, now)
    view = next(f for f in read_settings(env_settings).folders if f.kind is kind)
    events.publish(
        AgentSettingsChanged(
            change="folder",
            summary=f"{FOLDER_NAMES[kind]}: {_describe(view.resolved)}",
            triggered_by=triggered_by,
            folder=kind.value,
        )
    )
    return view


def set_harness(
    harness: Harness | None, triggered_by: str, events: EventPublisher, now: datetime
) -> None:
    """The harness every folder uses unless its own default picks the other.
    None: the environment's."""
    with write_transaction() as session:
        agent_settings_repo.save_harness(session, harness, now)
    events.publish(
        AgentSettingsChanged(
            change="harness",
            summary=f"Agent: {harness_name(harness) if harness else 'from the environment'}",
            triggered_by=triggered_by,
        )
    )


def set_runs_per_day(
    count: int | None, triggered_by: str, events: EventPublisher, now: datetime
) -> None:
    """Reviews and debriefs a day, together. None: the environment's."""
    if count is not None and not 1 <= count <= MAX_RUNS_PER_DAY:
        raise AgentSettingsError(f"runs a day must be from 1 to {MAX_RUNS_PER_DAY}, got {count}")
    with write_transaction() as session:
        agent_settings_repo.save_runs_per_day(session, count, now)
    events.publish(
        AgentSettingsChanged(
            change="runs_per_day",
            summary=f"Runs a day: {count if count is not None else 'from the environment'}",
            triggered_by=triggered_by,
        )
    )


def reset_to_env(triggered_by: str, events: EventPublisher, now: datetime) -> None:
    with write_transaction() as session:
        agent_settings_repo.clear(session)
    events.publish(
        AgentSettingsChanged(
            change="reset",
            summary="Every agent setting back to the environment",
            triggered_by=triggered_by,
        )
    )


def _describe(choice: RunChoice) -> str:
    parts = [
        harness_name(choice.harness) if choice.harness else None,
        choice.model or "default model",
        choice.effort or "default effort",
        f"${choice.max_budget_usd:.2f} cap" if choice.max_budget_usd is not None else None,
        f"{int(choice.timeout.total_seconds() // 60)} min" if choice.timeout else None,
    ]
    return ", ".join(part for part in parts if part)
