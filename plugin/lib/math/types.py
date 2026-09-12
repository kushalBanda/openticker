"""Plain data records shared across plugin/lib/math.

Ported from quant.core.interfaces, dropping the Signal/Setup Protocol
declarations - only the frozen dataclasses survive, since a skill script
dispatches to a compute function by name directly rather than through a
Protocol-typed object.
"""

from dataclasses import dataclass
from datetime import datetime


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
