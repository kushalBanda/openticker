"""A chat a page watches on the stream (ADR 40 in docs/adr): its turns' steps
as the agent works, and each turn asked, started or ended.

Each turn's steps are read from its event stream (core/agents/transcript.py),
only the bytes written since the last read, and a line only once it is
complete. The page is sent the steps from the first one that changed: a
tool's result arrives a line after its call.
"""

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from openticker.adapters.inbound.mcp_models import AgentJobResult, StepResult
from openticker.adapters.inbound.web.models import ThreadStepsMessage, ThreadTurnMessage
from openticker.core.agents import transcript
from openticker.core.agents.jobs import AgentJob, AgentJobStatus
from openticker.core.agents.transcript import Step
from openticker.storage import agent_job_files
from openticker.storage.sqlite import agent_jobs_repo


@dataclass
class _Tail:
    path: Path
    offset: int = 0
    partial: bytes = b""
    lines: list[str] = field(default_factory=list)
    sent: list[Step] = field(default_factory=list)

    def read(self) -> bool:
        """Whether a new complete line arrived."""
        try:
            with self.path.open("rb") as stream:
                stream.seek(self.offset)
                new = stream.read()
        except FileNotFoundError:
            return False
        self.offset += len(new)
        *complete, self.partial = (self.partial + new).split(b"\n")
        self.lines += [line.decode(errors="replace") for line in complete]
        return bool(complete)


class ThreadWatch:
    def __init__(self, thread_id: str) -> None:
        self.thread_id = thread_id
        self._statuses: dict[str, AgentJobStatus] | None = None  # None before the first poll
        self._tails: dict[str, _Tail] = {}

    def poll(self) -> list[BaseModel]:
        """What changed since the last poll. The first sends the steps of a
        turn still running, not turns the page has already read."""
        turns = agent_jobs_repo.turns_of(self.thread_id)
        first = self._statuses is None
        before = self._statuses or {}
        changed = [] if first else [job for job in turns if before.get(job.id) != job.status]
        self._statuses = {job.id: job.status for job in turns}
        messages: list[BaseModel] = []
        for job in turns:
            if job.status is AgentJobStatus.ENDED and job.id not in self._tails:
                continue
            message = self._steps(job)
            if message is not None:
                messages.append(message)
            if job.status is AgentJobStatus.ENDED:
                del self._tails[job.id]
        messages += [
            ThreadTurnMessage(thread_id=self.thread_id, turn=AgentJobResult.of(job, {}))
            for job in changed
        ]
        return messages

    def _steps(self, job: AgentJob) -> ThreadStepsMessage | None:
        tail = self._tails.setdefault(job.id, _Tail(agent_job_files.events_path(job.id)))
        if not tail.read():
            return None
        steps = transcript.read_steps(job.harness, tail.lines)
        start = next(
            (i for i, (old, new) in enumerate(zip(tail.sent, steps, strict=False)) if old != new),
            min(len(tail.sent), len(steps)),
        )
        if start == len(steps) == len(tail.sent):
            return None
        tail.sent = steps
        return ThreadStepsMessage(
            thread_id=self.thread_id,
            job_id=job.id,
            from_index=start,
            steps=[StepResult.of(step) for step in steps[start:]],
        )
