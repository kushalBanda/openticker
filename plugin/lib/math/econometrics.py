"""Standard time series analytics: returns, price reconstruction, series
normalization, annualization, rolling volatility, correlation and beta.

Ported verbatim from quant.features.econometrics.
"""

import math
from enum import Enum

import pandas as pd

from lib.math.exceptions import InsufficientDataError
from lib.math.statistics import annualization_factor


class ReturnKind(Enum):
    SIMPLE = "simple"
    LOGARITHMIC = "logarithmic"
    ABSOLUTE = "absolute"


def returns(x: pd.Series, kind: ReturnKind = ReturnKind.SIMPLE) -> pd.Series:
    if x.empty:
        return x
    shifted = x.shift(1)
    if kind == ReturnKind.SIMPLE:
        return x / shifted - 1
    if kind == ReturnKind.LOGARITHMIC:
        return x.apply(math.log) - shifted.apply(math.log)
    return x - shifted


def prices(x: pd.Series, initial: float = 1.0, kind: ReturnKind = ReturnKind.SIMPLE) -> pd.Series:
    if x.empty:
        return x
    if kind == ReturnKind.SIMPLE:
        return (1.0 + x).cumprod() * initial
    if kind == ReturnKind.LOGARITHMIC:
        return x.apply(math.exp).cumprod() * initial
    return x.cumsum() + initial


def index_normalize(x: pd.Series, initial: float = 1.0) -> pd.Series:
    first_idx = x.first_valid_index()
    if first_idx is None:
        return pd.Series(dtype=float)
    if not x.loc[first_idx]:
        raise InsufficientDataError("index_normalize needs a non-zero first value")
    result: pd.Series = initial * x / x.loc[first_idx]
    return result


def change(x: pd.Series) -> pd.Series:
    if x.empty:
        return x
    result: pd.Series = x - x.iloc[0]
    return result


def annualize(x: pd.Series) -> pd.Series:
    factor = annualization_factor(x.index)
    return x * math.sqrt(factor)


def volatility(x: pd.Series, window: int | None = None, assume_zero_mean: bool = False) -> pd.Series:
    """Rolling annualized realized volatility of a price series, in
    percent (20% annual vol returned as 20.0).
    """
    if x.size < 1:
        return x
    ret = returns(x)
    if window is None:
        vol = float((ret.pow(2)).mean()) ** 0.5 if assume_zero_mean else float(ret.std())
        vol_series = pd.Series(vol, index=x.index)
    else:
        if len(x) < window:
            raise InsufficientDataError(f"volatility needs at least {window} observations, got {len(x)}")
        vol_series = (
            ret.pow(2).rolling(window).mean().pow(0.5) if assume_zero_mean else ret.rolling(window).std()
        )
    factor = annualization_factor(x.index)
    return (vol_series * math.sqrt(factor)).mul(100)


def correlation(x: pd.Series, y: pd.Series) -> float:
    ret_x = returns(x).dropna()
    ret_y = returns(y).dropna()
    aligned = pd.concat([ret_x, ret_y], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        raise InsufficientDataError(f"correlation needs at least 2 aligned returns, got {len(aligned)}")
    result = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
    return float(result)


def beta(x: pd.Series, benchmark: pd.Series) -> float:
    ret_x = returns(x).dropna()
    ret_benchmark = returns(benchmark).dropna()
    aligned = pd.concat([ret_x, ret_benchmark], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        raise InsufficientDataError(f"beta needs at least 2 aligned returns, got {len(aligned)}")
    variance = float(aligned.iloc[:, 1].var())
    if variance == 0:
        raise InsufficientDataError("beta needs a benchmark with nonzero return variance")
    covariance = float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1]))
    return covariance / variance
