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


@dataclass(frozen=True)
class Tick:
    symbol: str
    ts: datetime
    price: float
    volume: int
    provider: str


@dataclass(frozen=True)
class IndexConstituent:
    index_name: str
    symbol: str
    year: int
    source: str
