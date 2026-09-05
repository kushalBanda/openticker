from datetime import datetime

from pydantic import BaseModel


class BarOut(BaseModel):
    symbol: str
    interval: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    provider: str


class BarListOut(BaseModel):
    bars: list[BarOut]


class IndexConstituentsOut(BaseModel):
    index_name: str
    year: int
    symbols: list[str]
