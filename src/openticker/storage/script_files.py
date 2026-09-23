"""Hosted scripts' files (ADR 25 in docs/adr): each script's source and one
log per run, under $OPENTICKER_HOME/scripts/<id>/. The directory is the
script's working directory and its HOME."""

import os
import shutil
from pathlib import Path

from openticker.storage.sqlite.engine import get_data_dir

SOURCE_NAME = "main.py"
_TAIL_BYTES = 262_144  # read from the end of a log to find its last lines


def script_dir(script_id: str) -> Path:
    return get_data_dir() / "scripts" / script_id


def script_path(script_id: str) -> Path:
    return script_dir(script_id) / SOURCE_NAME


def write_source(script_id: str, source: str) -> None:
    """Replaced whole, never half-written: a start at the same moment reads
    the old file or the new one."""
    directory = script_dir(script_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    staged = directory / (SOURCE_NAME + ".new")
    staged.write_text(source, encoding="utf-8")
    os.replace(staged, directory / SOURCE_NAME)


def read_source(script_id: str) -> str:
    return script_path(script_id).read_text(encoding="utf-8")


def delete_files(script_id: str) -> None:
    shutil.rmtree(script_dir(script_id), ignore_errors=True)


def log_path(script_id: str, run_id: str) -> Path:
    directory = script_dir(script_id) / "logs"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / f"{run_id}.log"


def append_log(script_id: str, run_id: str, line: str) -> None:
    with log_path(script_id, run_id).open("a", encoding="utf-8") as log:
        log.write(line + "\n")


def log_size(script_id: str, run_id: str) -> int:
    try:
        return log_path(script_id, run_id).stat().st_size
    except FileNotFoundError:
        return 0


def tail_log(script_id: str, run_id: str, lines: int) -> tuple[list[str], bool]:
    """The log's last `lines` lines, and whether earlier ones were left out."""
    path = log_path(script_id, run_id)
    try:
        with path.open("rb") as log:
            size = log.seek(0, os.SEEK_END)
            log.seek(max(0, size - _TAIL_BYTES))
            text = log.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return [], False
    found = text.splitlines()
    if size > _TAIL_BYTES:
        found = found[1:]  # the first may be a line cut in half
    return found[-lines:], size > _TAIL_BYTES or len(found) > lines


def prune_logs(script_id: str, keep: set[str]) -> None:
    """Deletes the logs of every run not in `keep`."""
    directory = script_dir(script_id) / "logs"
    if not directory.is_dir():
        return
    for path in directory.glob("*.log"):
        if path.stem not in keep:
            path.unlink(missing_ok=True)
