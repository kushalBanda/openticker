"""Each agent job's output under `$OPENTICKER_HOME/agent_jobs/` (ADR 29 in
docs/adr): what it printed while it worked, its event stream (ADR 40), and
its final answer."""

from pathlib import Path

from openticker.storage.sqlite.engine import get_data_dir

# The end of a log an answer carries (ADR 8 in docs/adr).
LOG_TAIL_BYTES = 32_768


def _folder() -> Path:
    folder = get_data_dir() / "agent_jobs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def log_path(job_id: str) -> Path:
    return _folder() / f"{job_id}.log"


def result_path(job_id: str) -> Path:
    return _folder() / f"{job_id}.result"


def events_path(job_id: str) -> Path:
    return _folder() / f"{job_id}.events.jsonl"


def read_events(job_id: str) -> list[str]:
    """Its event stream's lines; none when it has no stream."""
    try:
        return events_path(job_id).read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return []


def append_log(job_id: str, line: str) -> None:
    with log_path(job_id).open("a") as log:
        log.write(line + "\n")


def log_tail(job_id: str) -> tuple[str, bool]:
    """The end of its log, and whether older output was left out."""
    path = log_path(job_id)
    if not path.exists():
        return "", False
    size = path.stat().st_size
    with path.open("rb") as log:
        log.seek(max(size - LOG_TAIL_BYTES, 0))
        tail = log.read()
    return tail.decode(errors="replace"), size > LOG_TAIL_BYTES


def prune(keep: set[str]) -> None:
    """Deletes the output of every job not in `keep`."""
    for path in _folder().iterdir():
        job_id, _, suffix = path.name.partition(".")
        if job_id not in keep and suffix in ("log", "result", "events.jsonl"):
            path.unlink(missing_ok=True)
