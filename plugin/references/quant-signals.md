# Quant signals and features reference

`packages/quant` is a library, not a skill - every strategy in `packages/strategy` already consumes these directly (see `plugin/references/strategies.md`). This is background for Claude when reasoning about a strategy or a research report, not something a user runs standalone yet.

## Registered signals (`quant.signals`, built via `quant.core.registry.SignalFactory.create(name, config)`)

Each computes one `RawSignal` from a bar window and can `scale()` it into a `Forecast` (position-sizing conviction).

- **sma** (`SmaSignal(window)`) - moving average of closes over `window` bars.
- **rsi** (`RsiSignal(period)`) - relative strength index over `period` bars, 0-100 scale.
- **time_series_momentum** (`TimeSeriesMomentumSignal(window)`) - sign of the trailing `window`-bar return: +1.0 long, -1.0 short, 0.0 flat. Powers the `time_series_momentum` strategy.
- **above_average_volume** (`AboveAverageVolumeSignal(window)`) - today's volume vs. its trailing `window`-bar average, read as a potential near-term reversal signal (see `docs/features/swing-trading-signals.md`).

## Feature functions (`quant.features`, no registry - called directly)

**`technicals.py`** - price-series indicators, all take/return `pd.Series` unless noted:
- `moving_average(x, window)`, `smoothed_moving_average(x, window)`, `exponential_moving_average(x, beta)` - three moving-average variants.
- `bollinger_bands(x, window, k)` - returns a `pd.DataFrame` (lower/middle/upper bands).
- `relative_strength_index(x, window=14)` - 0-100 scale (not nautilus_trader's 0-1 scale, thresholds aren't interchangeable).
- `macd(x, m=12, n=26, s=1)`.
- `exponential_volatility(x, beta)`, `exponential_spread_volatility(x, beta)`.

**`econometrics.py`** - return/risk transforms:
- `returns(x, kind)`, `prices(x, initial, kind)`, `index_normalize(x, initial)`, `change(x)`, `annualize(x)`.
- `volatility(x, window=None, assume_zero_mean=False)` - rolling or full-sample realized volatility.
- `correlation(x, y)`, `beta(x, benchmark)`.

**`statistics.py`** - backtest performance metrics, used by `strategy.metrics.performance.compute_metrics`:
- `total_return(closes)`, `annualized_return(closes, risk_free_rate=0.0)`, `max_drawdown(closes)`, `sharpe_ratio(closes, risk_free_rate=0.0)`.
- `exponential_std(closes, beta=0.75)`, `exponential_std_series(returns, beta=0.75)`.
- `annualization_factor(index)` - infers bars-per-year from a `DatetimeIndex`'s spacing; raises `InsufficientDataError` when spacing is too irregular (the gap `run_backtest.py` reports as "performance metrics unavailable").

**`pairs.py`** - pairs-trading math, used by the `pairs_trading` strategy:
- `select_pairs(closes, top_n)` - ranks every symbol pair by formation-window sum-of-squared-deviation.
- `spread_baseline(closes_a, closes_b, anchor_a, anchor_b)`, `spread_value(price_a, price_b, anchor_a, anchor_b)`, `zscore(value, baseline)`.

## Evaluation (`quant.evaluation`)

- `evaluator.py` - `evaluate_signal(...)`: information-coefficient-style forward-return analysis for a signal, independent of running a full backtest.
- `forward_returns.py` - forward-return computation the evaluator consumes.

Not currently wrapped by any plugin skill or script - useful later if signal-quality analysis (as opposed to a full strategy backtest) becomes a real ask.
