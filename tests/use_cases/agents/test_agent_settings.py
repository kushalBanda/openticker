from datetime import timedelta
from pathlib import Path

import pytest

from openticker.adapters.inbound.daemon.agent_loop import AgentLoop
from openticker.core.agents.choices import FolderKind, RunChoice
from openticker.core.agents.jobs import AgentJobEndReason, AgentSettings, Harness
from openticker.core.agents.threads import Folder
from openticker.events.types import AgentSettingsChanged
from openticker.storage.sqlite import agent_jobs_repo
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.agents.manage import AgentJobCapError, start_review
from openticker.use_cases.agents.settings import (
    AgentSettingsError,
    read_settings,
    reset_to_env,
    resolved_settings,
    set_folder_choice,
    set_harness,
    set_runs_per_day,
)
from openticker.use_cases.agents.supervise import AgentContext
from openticker.use_cases.agents.threads import start_chat
from openticker.use_cases.strategies.define import create_strategy
from tests.fixtures.strategies import STRADDLE, list_nifty_market
from tests.use_cases.agents.test_agent_jobs import NOW, _Events, _Processes

ENV = AgentSettings(model="sonnet", effort="medium", jobs_per_day=5)


@pytest.fixture(autouse=True)
def _market() -> None:
    list_nifty_market()


def _loop(processes: _Processes, tmp_path: Path) -> AgentLoop:
    return AgentLoop(AgentContext(processes, _Events(), ENV, tmp_path, "u"), lambda: NOW)


def test_settings_show_what_is_stored_what_env_gives_and_what_runs() -> None:
    events = _Events()
    set_folder_choice(
        FolderKind.REVIEWS, RunChoice(model="opus", effort="high"), ENV, "ui", events, NOW
    )

    view = read_settings(ENV)

    reviews = next(f for f in view.folders if f.kind is FolderKind.REVIEWS)
    assert (reviews.stored.model, reviews.env.model, reviews.resolved.model) == (
        "opus",
        "sonnet",
        "opus",
    )
    assert reviews.resolved.effort == "high"
    general = next(f for f in view.folders if f.kind is FolderKind.GENERAL)
    assert general.stored == RunChoice() and general.resolved.model == "sonnet"
    [changed] = events.of(AgentSettingsChanged)
    assert changed.summary == "Reviews: Claude Code, opus, high, 15 min"  # type: ignore[attr-defined]


def test_a_choice_the_harness_doesnt_take_is_refused() -> None:
    with pytest.raises(AgentSettingsError, match="isn't an effort level"):
        set_folder_choice(FolderKind.GENERAL, RunChoice(effort="--yolo"), ENV, "ui", _Events(), NOW)
    set_harness(Harness.CODEX, "ui", _Events(), NOW)
    with pytest.raises(AgentSettingsError, match="no spend cap"):
        set_folder_choice(
            FolderKind.REVIEWS, RunChoice(max_budget_usd=1.0), ENV, "ui", _Events(), NOW
        )
    with pytest.raises(AgentSettingsError, match="from 1 to 500"):
        set_runs_per_day(0, "ui", _Events(), NOW)


def test_the_daemon_reads_new_settings_without_restart(tmp_path: Path) -> None:
    processes = _Processes()
    loop = _loop(processes, tmp_path)
    strategy = create_strategy("straddle", STRADDLE, NOW).id
    set_folder_choice(
        FolderKind.REVIEWS,
        RunChoice(model="opus", effort="max", max_budget_usd=0.8),
        ENV,
        "ui",
        _Events(),
        NOW,
    )

    review = start_review(strategy, resolved_settings(ENV), "ui", NOW)
    loop.step()

    [launch] = processes.launches
    assert (launch.job_id, launch.model, launch.effort, launch.max_budget_usd) == (
        review.id,
        "opus",
        "max",
        0.8,
    )
    stored = agent_jobs_repo.find_job(review.id)
    assert stored is not None and (stored.model, stored.effort) == ("opus", "max")


def test_a_folder_time_limit_holds_its_runs(tmp_path: Path) -> None:
    processes = _Processes()
    now = NOW
    loop = AgentLoop(AgentContext(processes, _Events(), ENV, tmp_path, "u"), lambda: now)
    set_folder_choice(
        FolderKind.GENERAL, RunChoice(timeout=timedelta(minutes=2)), ENV, "ui", _Events(), NOW
    )
    view = start_chat(Folder.GENERAL, None, "hi", None, None, resolved_settings(ENV), "ui", NOW)
    loop.step()

    now = NOW + timedelta(minutes=3)
    loop.step()

    job = agent_jobs_repo.find_job(view.turns[0].job.id)
    assert job is not None and job.end_reason is AgentJobEndReason.TIMEOUT
    assert job.end_detail == "still running after 2 minutes"


def test_a_chat_takes_its_folders_default_and_the_message_overrides_it() -> None:
    set_folder_choice(
        FolderKind.STRATEGIES,
        RunChoice(model="opus", effort="high"),
        ENV,
        "ui",
        _Events(),
        NOW,
    )
    strategy = create_strategy("straddle", STRADDLE, NOW).id
    settings = resolved_settings(ENV)

    folder = start_chat(Folder.STRATEGY, strategy, "why?", None, None, settings, "ui", NOW)
    general = start_chat(Folder.GENERAL, None, "hi", "haiku", None, settings, "ui", NOW)

    assert (folder.turns[0].job.model, folder.turns[0].job.effort) == ("opus", "high")
    assert (general.turns[0].job.model, general.turns[0].job.effort) == ("haiku", "medium")


def test_runs_a_day_from_settings_caps_reviews_and_reset_goes_back_to_env() -> None:
    set_runs_per_day(1, "ui", _Events(), NOW)
    first = create_strategy("one", STRADDLE, NOW).id
    second = create_strategy("two", STRADDLE, NOW).id
    job = start_review(first, resolved_settings(ENV), "ui", NOW)
    with write_transaction() as session:
        agent_jobs_repo.mark_started(session, job.id, NOW)
    with pytest.raises(AgentJobCapError, match="1 agent jobs"):
        start_review(second, resolved_settings(ENV), "ui", NOW)

    reset_to_env("ui", _Events(), NOW)

    assert resolved_settings(ENV).jobs_per_day == 5
    assert read_settings(ENV).runs_per_day is None


def test_a_model_chosen_for_claude_is_dropped_once_every_folder_runs_codex() -> None:
    events = _Events()
    plain = AgentSettings()  # Claude Code, no model or effort from the environment
    set_folder_choice(
        FolderKind.REVIEWS, RunChoice(model="opus", effort="max"), plain, "ui", events, NOW
    )
    set_folder_choice(
        FolderKind.DEBRIEFS, RunChoice(Harness.CLAUDE, "opus"), plain, "ui", events, NOW
    )

    set_harness(Harness.CODEX, "ui", events, NOW)

    folders = {f.kind: f for f in read_settings(plain).folders}
    reviews, debriefs = folders[FolderKind.REVIEWS], folders[FolderKind.DEBRIEFS]
    assert (reviews.resolved.harness, reviews.resolved.model, reviews.resolved.effort) == (
        Harness.CODEX,
        None,
        None,
    )
    assert (reviews.stored.model, reviews.stored.effort) == (None, None)
    # A folder that names its harness keeps it, and its model.
    assert (debriefs.resolved.harness, debriefs.resolved.model) == (Harness.CLAUDE, "opus")

    set_harness(None, "ui", events, NOW)  # back to the environment's Claude Code
    folders = {f.kind: f for f in read_settings(plain).folders}
    assert folders[FolderKind.REVIEWS].resolved.model == "opus"


def test_check_ins_are_set_apart_from_the_decisive_looks_on_the_managers_harness() -> None:
    events = _Events()
    set_folder_choice(
        FolderKind.MANAGER, RunChoice(model="opus", effort="high"), ENV, "ui", events, NOW
    )
    set_folder_choice(
        FolderKind.MANAGER_CHECKS, RunChoice(model="haiku", effort="low"), ENV, "ui", events, NOW
    )

    folders = {f.kind: f for f in read_settings(ENV).folders}

    assert folders[FolderKind.MANAGER_CHECKS].stored == RunChoice(model="haiku", effort="low")
    assert folders[FolderKind.MANAGER_CHECKS].resolved.model == "haiku"
    assert folders[FolderKind.MANAGER].resolved.model == "opus"
    assert [e.summary for e in events.of(AgentSettingsChanged)] == [  # type: ignore[attr-defined]
        "Manager: decisive looks: Claude Code, opus, high, 15 min",
        "Manager: check-ins: Claude Code, haiku, low, 15 min",
    ]
    with pytest.raises(AgentSettingsError, match="Manager's harness"):
        set_folder_choice(
            FolderKind.MANAGER_CHECKS, RunChoice(harness=Harness.CODEX), ENV, "ui", events, NOW
        )
