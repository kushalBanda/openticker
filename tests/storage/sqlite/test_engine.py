import sqlite3
from pathlib import Path

from sqlalchemy import inspect

from openticker.storage.sqlite.engine import get_engine

# sandbox_orders as versions before resting orders created it.
OLD_SANDBOX_ORDERS = (
    "CREATE TABLE sandbox_orders (order_id VARCHAR PRIMARY KEY, placed_at DATETIME, "
    "exchange VARCHAR, symbol VARCHAR, side VARCHAR, quantity INTEGER, product VARCHAR, "
    "order_type VARCHAR, status VARCHAR, fill_price FLOAT, reason VARCHAR, "
    "triggered_by VARCHAR, strategy_id VARCHAR, run_id VARCHAR)"
)


def test_columns_a_newer_version_added_are_added_to_an_older_database(tmp_path: Path) -> None:
    """A database from before resting orders existed: sandbox_orders without
    their columns, holding one filled order."""
    with sqlite3.connect(tmp_path / "openticker.db") as connection:
        connection.execute(OLD_SANDBOX_ORDERS)
        connection.execute(
            "INSERT INTO sandbox_orders VALUES ('SB1', '2026-09-21 05:00:00', 'NSE', 'RELIANCE', "
            "'BUY', 5, 'MIS', 'MARKET', 'FILLED', 1247.4, NULL, 'mcp', NULL, NULL)"
        )

    engine = get_engine()

    columns = {column["name"] for column in inspect(engine).get_columns("sandbox_orders")}
    assert {"price", "trigger_price", "triggered", "reserved_margin", "updated_at"} <= columns
    from openticker.storage.sqlite.sandbox_repo import list_orders

    [order] = list_orders(5)
    assert (order.order_id, order.reserved_margin, order.triggered) == ("SB1", 0.0, False)


def test_processes_starting_together_on_an_old_database_all_succeed(tmp_path: Path) -> None:
    """The MCP server and the daemon can start at the same moment; both must
    come up, whichever of them does the upgrade. Each process imports first,
    then waits for the same instant, so their first `get_engine()` calls collide."""
    import os
    import subprocess
    import sys
    import time

    with sqlite3.connect(tmp_path / "openticker.db") as connection:
        connection.execute(OLD_SANDBOX_ORDERS)
    environment = {**os.environ, "OPENTICKER_HOME": str(tmp_path)}
    start = time.time() + 2.0
    script = (
        "import sys, time\n"
        "from openticker.storage.sqlite.engine import get_engine\n"
        "time.sleep(max(0.0, float(sys.argv[1]) - time.time()))\n"
        "get_engine()\n"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(start)], env=environment, stderr=subprocess.PIPE
        )
        for _ in range(6)
    ]

    errors = [process.communicate()[1].decode() for process in processes]

    assert [process.returncode for process in processes] == [0] * 6, errors
