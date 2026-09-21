"""get_engine() — the one SQLite engine factory.

NullPool always, never StaticPool: overlapping tool calls run on separate
threads, and several OpenTicker processes can share this file. A single
shared connection's cursor state gets corrupted by concurrent access ("bad
parameter or other API misuse"). See ADR 2 in docs/adr.
"""

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from openticker.storage.sqlite.models import Base


def get_data_dir() -> Path:
    """Read at call time, not import time, so tests can override `OPENTICKER_HOME`."""
    return Path(os.environ.get("OPENTICKER_HOME", str(Path.home() / ".openticker")))


def get_engine() -> Engine:
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "openticker.db"
    engine = create_engine(f"sqlite:///{db_path}", poolclass=NullPool)
    Base.metadata.create_all(engine, checkfirst=True)  # no migrations tool yet — cheap, idempotent
    return engine
