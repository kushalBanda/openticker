import pandas as pd

from quant.core.exceptions import InsufficientDataError
from quant.features.econometrics import ReturnKind, annualize, returns
from quant.features.statistics import exponential_std_series

"""Technical analysis functions on price series: moving averages,
momentum, and volatility indicators. Pure pandas math, no external data
or network dependency.
"""


def moving_average(x: pd.Series, window: int | None = None) -> pd.Series:
    """Simple arithmetic moving average over `window` observations. Full
    series expanding mean if `window` is None.
    """
    if x.empty:
        return pd.Series(dtype=float)
    if window is None:
        return x.expanding().mean()
    if len(x) < window:
        raise InsufficientDataError(f"moving_average needs at least {window} observations, got {len(x)}")
    return x.rolling(window).mean()


def bollinger_bands(x: pd.Series, window: int | None = None, k: float = 2.0) -> pd.DataFrame:
    """Standard-deviation bands around the moving average of price level:
    upper = MA + k*sigma, middle = MA, lower = MA - k*sigma.
    """
    if x.empty:
        return pd.DataFrame({
            "lower": pd.Series(dtype=float),
            "middle": pd.Series(dtype=float),
            "upper": pd.Series(dtype=float),
        })
    avg = moving_average(x, window)
    sigma = x.expanding().std() if window is None else x.rolling(window).std()
    return pd.DataFrame({"lower": avg - k * sigma, "middle": avg, "upper": avg + k * sigma})


def smoothed_moving_average(x: pd.Series, window: int) -> pd.Series:
    """Wilder's modified/smoothed/running moving average (RMA):
    seeded with a flat mean over the first `window` observations, then
    recursively P_t = ((N-1)*P_{t-1} + X_t) / N for every observation
    after the seed.
    """
    if x.empty or len(x) < window:
        return pd.Series(dtype=float)
    means = x.rolling(window).mean()
    start = window - 1
    result = pd.Series(index=x.index, dtype=float)
    result.iloc[start] = means.iloc[start]
    for i in range(start + 1, len(x)):
        result.iloc[i] = ((window - 1) * result.iloc[i - 1] + x.iloc[i]) / window
    return result


def relative_strength_index(x: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index (RSI), Wilder's original recursive
    smoothing of average gains vs average losses.
    """
    if len(x) < window + 1:
        raise InsufficientDataError(f"relative_strength_index needs at least {window + 1} observations, got {len(x)}")
    one_period_change = x.diff().dropna()
    gains = one_period_change.clip(lower=0.0)
    losses = (-one_period_change).clip(lower=0.0)

    avg_gains = smoothed_moving_average(gains, window)
    avg_losses = smoothed_moving_average(losses, window)

    values: list[float] = []
    for position in range(len(avg_gains)):
        avg_gain = avg_gains.iloc[position]
        avg_loss = avg_losses.iloc[position]
        if pd.isna(avg_gain) or pd.isna(avg_loss):
            values.append(float("nan"))
        elif avg_loss == 0:
            values.append(100.0)
        else:
            relative_strength = avg_gain / avg_loss
            values.append(100 - (100 / (1 + relative_strength)))
    return pd.Series(values, index=avg_gains.index, dtype=float)


def exponential_moving_average(x: pd.Series, beta: float = 0.75) -> pd.Series:
    """Exponentially weighted moving average, `beta` the weight placed on
    the previous average (higher beta = more weight on the past).
    """
    return x.ewm(alpha=1 - beta, adjust=False).mean()


def macd(x: pd.Series, m: int = 12, n: int = 26, s: int = 1) -> pd.Series:
    """Moving average convergence divergence: EMA(m) - EMA(n), optionally
    smoothed again with an EMA of span `s` (default 1, no extra smoothing).
    """
    fast = x.ewm(adjust=False, span=m).mean()
    slow = x.ewm(adjust=False, span=n).mean()
    return (fast - slow).ewm(adjust=False, span=s).mean()


def exponential_volatility(x: pd.Series, beta: float = 0.75) -> pd.Series:
    """Exponentially weighted, annualized volatility of `x`'s simple
    returns, in percent.
    """
    ret = returns(x, ReturnKind.SIMPLE)
    ewm_std = exponential_std_series(ret, beta)
    return annualize(ewm_std).mul(100)


def exponential_spread_volatility(x: pd.Series, beta: float = 0.75) -> pd.Series:
    """Exponentially weighted, annualized volatility of `x`'s absolute
    (spread) differences.
    """
    diffs = returns(x, ReturnKind.ABSOLUTE)
    ewm_std = exponential_std_series(diffs, beta)
    return annualize(ewm_std)
