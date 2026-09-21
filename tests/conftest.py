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
