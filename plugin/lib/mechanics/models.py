"""Flat market-data types shared by every skill script.

Ported from ingest.core.models. Tick and IndexConstituent are dropped:
no skill script writes ticks or index constituents (see the design spec's
"not ported" list), so only Bar survives.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Bar:
    symbol: str
    interval: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    provider: str
