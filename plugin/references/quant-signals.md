# Quant signals and features reference

`plugin/lib/math` is the shared math library every skill script and strategy calls into directly - flat functions, no registry, no class hierarchy. This is background for Claude when reasoning about a strategy, a signal evaluation, or a research report.

## Signals (`lib.math.indicators`)

Each `compute_*` function takes a bar window and returns a `RawSignal` (symbol/interval/ts/name/value); each has a matching `scale_*` function that turns that into a `Forecast` (position-sizing conviction, `scaled_value` on a -20..+20 range).

- **compute_sma(bars, window)** - moving average of closes over `window` bars. `scale_sma` is a documented pass-through (a price level has no natural -20..+20 mapping).
- **compute_rsi(bars, period)** - relative strength index over `period` bars, 0-100 scale (see the formula below). `scale_rsi` maps linearly: `scaled = (value - 50) * (20 / 50)`.
- **compute_time_series_momentum(bars, window)** - sign of the trailing `window`-bar return: +1.0 long, -1.0 short, 0.0 flat. `scale_time_series_momentum` scales straight to `value * 20.0` (sign is already full conviction).
- **compute_above_average_volume(bars, window)** - today's volume vs. its trailing `window`-bar average, read as a potential near-term reversal signal (see `docs/features/swing-trading-signals.md`). `scale_above_average_volume` is a documented pass-through (already a bounded ratio).

`FORECAST_SCALE_MAX`/`MIN` = ±20.0, `RSI_MIDPOINT` = 50.0 (`lib.math.constants`).

## Feature functions (`lib.math`, no registry, called directly)

**`technicals.py`** - price-series indicators, all take/return `pd.Series` unless noted:
- `moving_average(x, window)` - simple mean over `window`, or full-series expanding mean if `window` is `None`.
- `smoothed_moving_average(x, window)` - Wilder's RMA: seeded with a flat mean over the first `window` observations, then recursively `P_t = ((N-1)*P_{t-1} + X_t) / N` for every observation after the seed.
- `exponential_moving_average(x, beta)` - `x.ewm(alpha=1-beta, adjust=False).mean()`.
- `bollinger_bands(x, window, k)` - returns a `pd.DataFrame` (lower/middle/upper bands): `upper = MA + k*sigma`, `lower = MA - k*sigma`.
- `relative_strength_index(x, window=14)` - Wilder's original recursive smoothing of average gains vs average losses, seeded via `smoothed_moving_average`. 0-100 scale (not nautilus_trader's 0-1 scale, thresholds aren't interchangeable). A flat-price window degenerates to exactly 100.0, not NaN, via the `avg_loss == 0` branch - a real edge case, not a bug, worth knowing before reading a suspiciously round RSI value.
- `macd(x, m=12, n=26, s=1)` - `EMA(m) - EMA(n)`, optionally smoothed again with an EMA of span `s`.
- `exponential_volatility(x, beta)`, `exponential_spread_volatility(x, beta)`.

**`econometrics.py`** - return/risk transforms:
- `returns(x, kind)`, `prices(x, initial, kind)`, `index_normalize(x, initial)`, `change(x)`, `annualize(x)`.
- `volatility(x, window=None, assume_zero_mean=False)` - rolling or full-sample realized volatility, in percent.
- `correlation(x, y)`, `beta(x, benchmark)`.

**`statistics.py`** - backtest performance metrics, used by `lib.math.performance.compute_metrics`:
- `total_return(closes)` - simple total return, start to end, not annualized.
- `annualized_return(closes, risk_free_rate=0.0)` - compound annualized return, Actual/365.25 day count on real elapsed calendar time. `risk_free_rate`, if given, is removed from the return day by day (Actual/360) before annualizing.
- `max_drawdown(closes)` - largest peak-to-trough decline, as a negative fraction (e.g. -0.25 for a 25% drawdown), zero if the series never falls below a prior peak.
- `sharpe_ratio(closes, risk_free_rate=0.0)` - annualized excess return over annualized volatility (sample stdev, N-1), both derived from real elapsed calendar time, times 100. Needs at least 3 closes.
- `exponential_std(closes, beta=0.75)`, `exponential_std_series(returns, beta=0.75)` - exponentially weighted stdev, `beta` must be in `[0, 1)`, matching `ewm(alpha=1-beta, adjust=False).std()`.
- `annualization_factor(index)` - infers bars-per-year from a `DatetimeIndex`'s average spacing: <2.1 days -> 252 (daily), 6-8 -> 52 (weekly), 14-17 -> 26 (semi-monthly), 25-35 -> 12 (monthly), 85-97 -> 4 (quarterly), 360-386 -> 1 (annual); raises `InsufficientDataError` outside those bands (the gap `run_backtest.py`'s script reports as "performance metrics unavailable").

**`pairs.py`** - pairs-trading math, used by the `pairs_trading` strategy:
- `select_pairs(closes, top_n)` - ranks every symbol pair by formation-window sum-of-squared-deviation over each series normalized to its first value.
- `spread_baseline(closes_a, closes_b, anchor_a, anchor_b)` - mean/std of the normalized spread over the formation window.
- `spread_value(price_a, price_b, anchor_a, anchor_b)`, `zscore(value, baseline)` - single-point spread and its z-score against the frozen baseline, never re-anchored mid trading period.

## Signal evaluation (`lib.math.evaluation`)

- `evaluate_signal_ic(compute, signal_name, bars, horizon, min_lookback)` - Spearman information-coefficient read on whether a signal's raw value predicts the `horizon`-bar forward return. Needs at least `MIN_SAMPLE_SIZE = 30` valid (signal, forward return) pairs, raises `InsufficientDataError` otherwise.
- `forward_returns(bars, horizon)` - the `horizon`-bar forward return for every bar: `close[i+horizon]/close[i] - 1`. The last `horizon` entries are `None`.
- **Overlapping-windows caveat**: `information_coefficient`/`ic_p_value` are computed on overlapping N-day forward-return windows; consecutive samples share most of their days and are not independent, so `ic_p_value` understates the true uncertainty. `effective_ic_p_value`, computed on a non-overlapping subsample of `effective_sample_size` points, is the more honest number to judge significance against.

Wired into the `evaluate-signal` skill's script (`plugin/skills/evaluate-signal/scripts/evaluate_signal.py`).

## Position sizing (`lib.math.sizing`)

- `PositionSizer(target_risk_pct).size(forecast, volatility, account_equity, price)` - volatility-targeted sizing: conviction is `forecast.scaled_value / FORECAST_SCALE_MAX` clamped to `[-1, 1]`; `max_shares_at_full_risk = (target_risk_pct * account_equity) / (volatility * price)`; signed shares = that times conviction. Correlation adjustment across open positions is not implemented - single-instrument only.
- `capital_to_quantity(capital, price)` - whole shares affordable with `capital` at `price`, floored, never negative. Used by `pairs_trading` and `time_series_momentum` to turn a cash budget into an order quantity.
