"""get_engine() — the one SQLite engine factory.

NullPool always, never StaticPool: overlapping tool calls run on separate
threads, and several OpenTicker processes can share this file. A single
shared connection's cursor state gets corrupted by concurrent access ("bad
parameter or other API misuse"). See ADR 2 in docs/adr.
"""

import os
import threading
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.pool import NullPool

from openticker.storage.sqlite.models import Base

_prepared: set[Path] = set()
_prepare_lock = threading.Lock()


def get_data_dir() -> Path:
    """Read at call time, not import time, so tests can override `OPENTICKER_HOME`.
    Always absolute: a hosted script's process gets this as its `cwd` and its
    file path as an argument (ADR 25), and a relative `OPENTICKER_HOME` would
    make the child resolve that path against its own (already-moved) cwd."""
    return Path(os.environ.get("OPENTICKER_HOME", str(Path.home() / ".openticker"))).resolve()


def get_engine() -> Engine:
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "openticker.db"
    engine = create_engine(f"sqlite:///{db_path}", poolclass=NullPool)
    with _prepare_lock:
        if db_path not in _prepared or not db_path.exists():
            _prepare(engine)
            _prepared.add(db_path)
    return engine


def _prepare(engine: Engine) -> None:
    """Creates missing tables, and adds columns and indexes a newer version
    introduced to tables an older one created. Only additive, nullable
    changes are made this way; anything else needs a real migration (ADR 18
    in docs/adr)."""
    # Under the write lock (BEGIN IMMEDIATE): the MCP server and the daemon
    # can start together, and each must see the other's changes before
    # deciding what is missing.
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        Base.metadata.create_all(connection, checkfirst=True)
        existing = inspect(connection)
        for table in Base.metadata.sorted_tables:
            present = {column["name"] for column in existing.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable:
                    raise RuntimeError(
                        f"{table.name}.{column.name} is new and not nullable: it needs a migration"
                    )
                kind = column.type.compile(dialect=engine.dialect)
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {kind}'
                )
            for index in table.indexes:  # an index on an old table is added too
                index.create(connection, checkfirst=True)
        connection.commit()
