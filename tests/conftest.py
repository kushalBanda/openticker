from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets its own data dir — nothing ever touches the real ~/.openticker."""
    monkeypatch.setenv("OPENTICKER_HOME", str(tmp_path))


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip notification settings a developer's shell may export, so no test
    can post to a real Slack channel or mailbox."""
    for name in ("SLACK_WEBHOOK_URL", "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _default_agent_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent job settings a developer's shell may export don't reach tests."""
    for name in (
        "OPENTICKER_AGENT_HARNESS",
        "OPENTICKER_AGENT_TIMEOUT_MINUTES",
        "OPENTICKER_AGENT_JOBS_PER_DAY",
        "OPENTICKER_AGENT_MAX_BUDGET_USD",
        "OPENTICKER_LABS_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
