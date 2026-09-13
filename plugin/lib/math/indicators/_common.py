"""Shared shape for every wrapped `ta` indicator in this package: the
latest value plus a short trailing window, so the agent can see whether
a reading is rising, falling, or flat - not just its current value.
"""

from dataclasses import dataclass

import pandas as pd

from lib.math.exceptions import InsufficientDataError

DEFAULT_TRAILING_COUNT = 5


@dataclass(frozen=True)
class TrailingReading:
    latest: float
    trailing: list[float]


def _trailing_reading(series: pd.Series, trailing_count: int = DEFAULT_TRAILING_COUNT) -> TrailingReading:
    clean = series.dropna()
    if clean.empty:
        raise InsufficientDataError("indicator produced no valid values for the given bars")
    latest = float(clean.iloc[-1])
    trailing = [float(v) for v in clean.iloc[-trailing_count:]]
    return TrailingReading(latest=latest, trailing=trailing)
