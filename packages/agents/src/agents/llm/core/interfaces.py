from dataclasses import dataclass
from typing import Any

# A single chat message: {"role": "system"|"user"|"assistant", "content": "..."}.
Message = dict[str, str]


@dataclass(frozen=True)
class LLMResponse:
    """Normalized result of one completion call."""

    content: str
    model: str
    raw: Any
