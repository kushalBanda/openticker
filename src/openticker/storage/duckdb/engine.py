"""get_connection() — a fresh DuckDB connection per call, file under the same
data dir as SQLite.

Per call, never held open: DuckDB lets only one process hold a read-write
handle on a file at a time, and several OpenTicker processes (one MCP server
per agent session) can run at once. Callers use it as a context manager so
the handle is released as soon as the read or write finishes. One at a time
within a process: two connections open together conflict on the schema and
on the rows they both write, so a second caller waits. See ADR 3 in docs/adr.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import duckdb

from openticker.storage.sqlite.engine import get_data_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    exchange   VARCHAR   NOT NULL,
    symbol     VARCHAR   NOT NULL,
    interval   VARCHAR   NOT NULL,
    timestamp  TIMESTAMP NOT NULL,  -- UTC, stored naive; tz is re-attached at the repo boundary
    open       DOUBLE    NOT NULL,
    high       DOUBLE    NOT NULL,
    low        DOUBLE    NOT NULL,
    close      DOUBLE    NOT NULL,
    volume     BIGINT    NOT NULL,
    PRIMARY KEY (exchange, symbol, interval, timestamp)
)
"""


_ONE_AT_A_TIME = threading.Lock()


@contextmanager
def get_connection() -> Iterator[duckdb.DuckDBPyConnection]:
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    with _ONE_AT_A_TIME:
        connection = duckdb.connect(str(data_dir / "bars.duckdb"))
        try:
            connection.execute(_SCHEMA)  # no migrations tool yet — cheap, idempotent
            yield connection
        finally:
            connection.close()
