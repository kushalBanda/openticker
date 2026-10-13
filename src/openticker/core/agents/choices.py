"""What a run of the user's coding agent uses (ADR 40 in docs/adr): which
harness, model and effort, and for how long and how much. Each folder kind
has a default, set in the web app's Settings; a chat can override the model
and effort for one message. Each field comes from the most specific level
that sets it: the message, the folder's default, the default harness Settings
picked, then the server's environment. Unset everywhere, the harness's own
default runs. Pure."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
from enum import StrEnum

from openticker.core.agents.jobs import AgentJobError, AgentJobKind, AgentSettings, Harness
from openticker.core.agents.threads import Folder

# How hard the agent thinks: a level name as the harness takes it ("low",
# "max"). Which levels there are is each model's, as its harness lists it
# (core/agents/catalog.py), never a list kept here. The name goes on the
# harness's command line, so it is held to a plain word.
Effort = str
_EFFORT = re.compile(r"[a-z][a-z0-9_-]{0,15}")


def check_effort(effort: str) -> str:
    if not _EFFORT.fullmatch(effort):
        raise AgentJobError(f"{effort!r} isn't an effort level: a lowercase word, at most 16")
    return effort


@dataclass(frozen=True)
class ModelOption:
    """A model a harness offers, as the harness itself lists it on this
    machine (adapters/agents/harness.py): never a list kept here, since both
    ship new models often. `id` is what goes to `--model`: an alias or a
    full name; `resolves_to` is the full name an alias runs today, when the
    harness says."""

    id: str
    name: str  # as the harness shows it
    about: str  # what the harness says it's for
    resolves_to: str | None = None
    efforts: tuple[Effort, ...] = ()  # the levels it takes, lowest first; (): none
    default_effort: Effort | None = None  # what it runs with none named, if the harness says


MAX_RUNS_PER_DAY = 500


class FolderKind(StrEnum):
    """Where a run starts, each with its own default."""

    GENERAL = "general"
    STRATEGIES = "strategies"
    SCRIPTS = "scripts"
    REVIEWS = "reviews"
    DEBRIEFS = "debriefs"


@dataclass(frozen=True)
class RunChoice:
    """None everywhere means "not set at this level"."""

    harness: Harness | None = None
    model: str | None = None
    effort: Effort | None = None
    max_budget_usd: float | None = None  # Claude Code only
    timeout: timedelta | None = None


@dataclass(frozen=True)
class StoredSettings:
    """What the web app's Settings set. None: from the environment."""

    harness: Harness | None = None
    runs_per_day: int | None = None
    choices: Mapping[FolderKind, RunChoice] = field(default_factory=dict)
    # The harness each folder's model and effort were chosen for.
    chosen_for: Mapping[FolderKind, Harness] = field(default_factory=dict)


def stored_choice(stored: StoredSettings, kind: FolderKind, env_harness: Harness) -> RunChoice:
    """A folder's own choice as it applies now: a model and effort chosen for
    one harness are dropped once every folder runs the other, unless the
    folder names its harness itself."""
    choice = stored.choices.get(kind, RunChoice())
    meant = stored.chosen_for.get(kind)
    if (
        choice.harness is None
        and meant is not None
        and meant is not (stored.harness or env_harness)
    ):
        return replace(choice, model=None, effort=None)
    return choice


def resolve(*levels: RunChoice, default_harness: Harness) -> RunChoice:
    """Each field from the first level that sets it, most specific first. A
    level that names a harness other than the one chosen gives nothing else:
    one harness's model or effort means nothing to the other. A spend cap on
    Codex is passed over."""
    harness = next((level.harness for level in levels if level.harness), default_harness)
    usable = [level for level in levels if level.harness in (None, harness)]
    effort = next((level.effort for level in usable if level.effort), None)
    budget = (
        next((lvl.max_budget_usd for lvl in usable if lvl.max_budget_usd is not None), None)
        if harness is Harness.CLAUDE
        else None
    )
    return RunChoice(
        harness=harness,
        model=next((level.model for level in usable if level.model), None),
        effort=effort,
        max_budget_usd=budget,
        timeout=next((level.timeout for level in usable if level.timeout), None),
    )


def check_choice(choice: RunChoice, harness: Harness) -> None:
    """A choice someone made, for a run of `harness`: refused with a reason
    rather than passed over."""
    if choice.effort is not None:
        check_effort(choice.effort)
    if choice.model is not None and not choice.model.strip():
        raise AgentJobError("the model can't be blank: leave it out for the default")
    if choice.max_budget_usd is not None:
        if harness is not Harness.CLAUDE:
            raise AgentJobError(f"{harness} has no spend cap: only Claude Code takes one")
        if choice.max_budget_usd <= 0:
            raise AgentJobError(f"the spend cap must be above 0, got {choice.max_budget_usd}")
    if choice.timeout is not None and choice.timeout < timedelta(minutes=1):
        raise AgentJobError(f"the time limit must be at least a minute, got {choice.timeout}")


def env_choice(settings: AgentSettings) -> RunChoice:
    """What the server's environment gives (OPENTICKER_AGENT_*)."""
    return RunChoice(
        harness=settings.harness,
        model=settings.model,
        effort=settings.effort,
        max_budget_usd=settings.max_budget_usd,
        timeout=settings.timeout,
    )


def run_choice(settings: AgentSettings, kind: FolderKind) -> RunChoice:
    """What a run in `kind` uses with no override: Settings' resolved choice,
    or the environment's when Settings weren't read."""
    found = settings.choices.get(kind)
    return found if found is not None else env_choice(settings)


def resolved_choices(
    stored: StoredSettings, settings: AgentSettings
) -> dict[FolderKind, RunChoice]:
    env = env_choice(settings)
    default = RunChoice(harness=stored.harness)
    return {
        kind: resolve(
            stored_choice(stored, kind, settings.harness),
            default,
            env,
            default_harness=settings.harness,
        )
        for kind in FolderKind
    }


_FOLDER_KINDS: Mapping[Folder, FolderKind] = {
    Folder.GENERAL: FolderKind.GENERAL,
    Folder.STRATEGY: FolderKind.STRATEGIES,
    Folder.SCRIPT: FolderKind.SCRIPTS,
    Folder.REVIEW: FolderKind.REVIEWS,
    Folder.DEBRIEF: FolderKind.DEBRIEFS,
}


def folder_kind(folder: Folder) -> FolderKind:
    return _FOLDER_KINDS[folder]


def job_kind_folder(kind: AgentJobKind) -> FolderKind | None:
    """A background job's folder kind; None for a chat, whose thread says."""
    if kind is AgentJobKind.REVIEW:
        return FolderKind.REVIEWS
    if kind is AgentJobKind.DEBRIEF:
        return FolderKind.DEBRIEFS
    return None
