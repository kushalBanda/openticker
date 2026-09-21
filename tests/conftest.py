from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets its own data dir — nothing ever touches the real ~/.openticker."""
    monkeypatch.setenv("OPENTICKER_HOME", str(tmp_path))
