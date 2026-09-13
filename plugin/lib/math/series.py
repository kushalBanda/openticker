"""Converts a list[Bar] into the pandas.Series shape every function in
plugin/lib/math expects.

Ported verbatim from quant.core.series.
"""

import pandas as pd

from lib.mechanics.models import Bar


def bar_closes_to_series(bars: list[Bar]) -> pd.Series:
    return pd.Series(
        [bar.close for bar in bars],
        index=pd.DatetimeIndex([bar.ts for bar in bars]),
        dtype=float,
    )


def bar_volumes_to_series(bars: list[Bar]) -> pd.Series:
    return pd.Series(
        [float(bar.volume) for bar in bars],
        index=pd.DatetimeIndex([bar.ts for bar in bars]),
        dtype=float,
    )


def bar_highs_to_series(bars: list[Bar]) -> pd.Series:
    return pd.Series(
        [bar.high for bar in bars],
        index=pd.DatetimeIndex([bar.ts for bar in bars]),
        dtype=float,
    )


def bar_lows_to_series(bars: list[Bar]) -> pd.Series:
    return pd.Series(
        [bar.low for bar in bars],
        index=pd.DatetimeIndex([bar.ts for bar in bars]),
        dtype=float,
    )
