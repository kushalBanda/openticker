"""get_connection() — a fresh DuckDB connection per call, file under the same
data dir as SQLite.

Per call, never held open: DuckDB lets only one process hold a read-write
handle on a file at a time, and several OpenTicker processes (one MCP server
per agent session) can run at once. Callers use it as a context manager so
the handle is released as soon as the read or write finishes. See ADR 3 in docs/adr.
"""

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


def get_connection() -> duckdb.DuckDBPyConnection:
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(data_dir / "bars.duckdb"))
    connection.execute(_SCHEMA)  # no migrations tool yet — cheap, idempotent
    return connection
