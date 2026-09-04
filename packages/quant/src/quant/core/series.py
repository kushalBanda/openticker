import pandas as pd
from ingest.core.models import Bar


def bar_closes_to_series(bars: list[Bar]) -> pd.Series:
    """`bars`' close prices as a float Series indexed by bar timestamp,
    the shape every function in `quant.features` expects."""
    return pd.Series(
        [bar.close for bar in bars],
        index=pd.DatetimeIndex([bar.ts for bar in bars]),
        dtype=float,
    )


def bar_volumes_to_series(bars: list[Bar]) -> pd.Series:
    """`bars`' volumes as a float Series indexed by bar timestamp, the
    shape every function in `quant.features` expects."""
    return pd.Series(
        [float(bar.volume) for bar in bars],
        index=pd.DatetimeIndex([bar.ts for bar in bars]),
        dtype=float,
    )
