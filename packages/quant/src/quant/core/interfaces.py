from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ingest.core.models import Bar


@dataclass(frozen=True)
class RawSignal:
    symbol: str
    interval: str
    ts: datetime
    name: str
    value: float


@dataclass(frozen=True)
class Forecast:
    symbol: str
    interval: str
    ts: datetime
    name: str
    scaled_value: float


@dataclass(frozen=True)
class PositionSize:
    symbol: str
    interval: str
    ts: datetime
    name: str
    size: float
    risk_pct: float


class Signal(Protocol):
    name: str

    def compute(self, bars: list[Bar]) -> RawSignal: ...

    def scale(self, raw: RawSignal) -> Forecast: ...
