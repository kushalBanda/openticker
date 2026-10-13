from datetime import timedelta

import pytest

from openticker.core.agents.choices import (
    FolderKind,
    RunChoice,
    StoredSettings,
    check_choice,
    folder_kind,
    resolve,
    resolved_choices,
    run_choice,
)
from openticker.core.agents.jobs import AgentJobError, AgentSettings, Harness
from openticker.core.agents.threads import Folder

CLAUDE, CODEX = Harness.CLAUDE, Harness.CODEX


def test_resolve_takes_each_field_from_the_most_specific_level() -> None:
    override = RunChoice(model="haiku")
    stored = RunChoice(model="opus", effort="high")
    env = RunChoice(harness=CLAUDE, effort="low", max_budget_usd=0.5, timeout=timedelta(minutes=9))

    assert resolve(override, stored, env, default_harness=CLAUDE) == RunChoice(
        CLAUDE, "haiku", "high", 0.5, timedelta(minutes=9)
    )


def test_a_level_for_the_other_harness_gives_nothing_but_its_harness() -> None:
    env = RunChoice(harness=CLAUDE, model="opus", effort="max", max_budget_usd=1.0)

    chosen = resolve(RunChoice(harness=CODEX), env, default_harness=CLAUDE)

    assert chosen == RunChoice(harness=CODEX)  # no Claude model, effort or spend cap on Codex


def test_effort_comes_from_the_most_specific_level_that_sets_one() -> None:
    levels = (RunChoice(effort="xhigh"), RunChoice(effort="medium"))

    assert resolve(*levels, default_harness=CODEX).effort == "xhigh"
    assert resolve(RunChoice(), *levels, default_harness=CLAUDE).effort == "xhigh"


def test_check_choice_refuses_what_the_harness_doesnt_take() -> None:
    # Which levels a model takes is its harness's to say (core/agents/catalog.py);
    # here only that it's a plain word, since it goes on the command line.
    for bad in ("--yolo", "High; rm", ""):
        with pytest.raises(AgentJobError, match="isn't an effort level"):
            check_choice(RunChoice(effort=bad or "x" * 17), CODEX)
    with pytest.raises(AgentJobError, match="no spend cap"):
        check_choice(RunChoice(max_budget_usd=1.0), CODEX)
    with pytest.raises(AgentJobError, match="at least a minute"):
        check_choice(RunChoice(timeout=timedelta(seconds=30)), CLAUDE)
    with pytest.raises(AgentJobError, match="blank"):
        check_choice(RunChoice(model="  "), CLAUDE)
    check_choice(RunChoice(CODEX, "gpt-5-codex", "minimal"), CODEX)


def test_folders_resolve_stored_then_settings_harness_then_env() -> None:
    env = AgentSettings(model="sonnet", effort="medium", max_budget_usd=2.0)
    stored = StoredSettings(
        harness=None, choices={FolderKind.REVIEWS: RunChoice(model="opus", effort="high")}
    )

    choices = resolved_choices(stored, env)

    assert choices[FolderKind.REVIEWS] == RunChoice(
        CLAUDE, "opus", "high", 2.0, timedelta(minutes=15)
    )
    assert choices[FolderKind.GENERAL] == RunChoice(
        CLAUDE, "sonnet", "medium", 2.0, timedelta(minutes=15)
    )
    # Settings pick Codex for every folder: the environment's Claude choices drop out.
    codex = resolved_choices(StoredSettings(harness=CODEX), env)[FolderKind.GENERAL]
    assert codex == RunChoice(harness=CODEX)


def test_without_settings_read_a_run_takes_the_environments_choice() -> None:
    env = AgentSettings(model="haiku", effort="low")

    assert run_choice(env, FolderKind.DEBRIEFS) == RunChoice(
        CLAUDE, "haiku", "low", None, timedelta(minutes=15)
    )
    assert folder_kind(Folder.STRATEGY) is FolderKind.STRATEGIES
