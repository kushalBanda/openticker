# scan-market and technical-screen formulas

Background for the scan-market, technical-screen, and position-sizing skills. Read this when you need the exact rule or typical use behind a
reading, not during normal use. Every function listed takes its window/threshold as a keyword argument with a default - none of these
values are fixed inside the function.

Trend, momentum, volatility, and volume readings (except `above_average_volume` and `vwap`) are thin wrappers around
[`ta`](https://github.com/bukosabino/ta), a maintained, widely-used Python technical-analysis library - not hand-rolled math. Structure and cross-sectional readings are hand-rolled, since `ta` has no equivalent for any of them. Every wrapped `ta` reading returns a `TrailingReading` (`latest` plus a short `trailing` window of recent values, default 5), so a plain number is never the whole picture - the trend of the reading itself is visible too. 

## Trend (`plugin/lib/math/indicators/trend.py`, wraps `ta.trend`)

- `sma` / `ema` / `wma` (default window 20/20/9) - moving averages.
- `macd` (window_slow=26, window_fast=12, window_sign=9) - EMA(fast)
  minus EMA(slow), plus a signal line and histogram. Classic
  trend-momentum crossover.
- `adx` (window=14) - Wilder's trend-strength indicator, returns
  `adx`/`plus_di`/`minus_di`. `plus_di > minus_di` favors an uptrend;
  `adx` above roughly 25 is conventionally read as "trending," below as
  "range-bound," though that threshold is a convention, not a rule this
  code enforces.
- `parabolic_sar` (step=0.02, max_step=0.2) - Wilder's stop-and-reverse
  level.

## Momentum (`plugin/lib/math/indicators/momentum.py`, wraps `ta.momentum`/`ta.trend`)

- `rsi` (window=14) - Wilder's relative strength index, 0 to 100.
- `stochastic` (window=14, smooth_window=3) - %K/%D oscillator.
- `stochastic_rsi` (window=14, smooth1=3, smooth2=3) - RSI applied to a
  rolling window of RSI values, with its own %K/%D smoothing.
- `williams_r` (lbp=14) - inverse-scaled version of stochastic %K.
- `roc` (window=12) - percent change over the window.
- `cci` (window=20, constant=0.015) - Lambert's Commodity Channel Index.

## Volatility (`plugin/lib/math/indicators/volatility.py`, Bollinger/ATR wrap `ta.volatility`)

- `bollinger_bands` (window=20, window_dev=2) - stdev bands around a
  simple moving average.
- `atr` (window=14) - Wilder-smoothed Average True Range.
- `realized_volatility` (window=20, annualization_factor=252) - hand-
  rolled (no `ta` equivalent), annualized standard deviation of simple
  returns (sourced from `ta.others.DailyReturnIndicator`), in percent.

## Volume (`plugin/lib/math/indicators/volume.py`, OBV/A-D wrap `ta.volume`)

- `above_average_volume` (window=20) - hand-rolled (no `ta` equivalent):
  last bar's volume divided by the window average.
- `obv` - cumulative On-Balance Volume. `ta`'s convention seeds
  accumulation from the first bar's own volume, not zero.
- `vwap` - hand-rolled (`ta`'s `VolumeWeightedAveragePrice` is a
  fixed-window rolling average, a different concept): volume-weighted
  average price over whatever bar window is passed in, no fixed period,
  since VWAP is normally computed over one session, pass exactly the
  bars you mean.
- `accumulation_distribution` - cumulative Accumulation/Distribution
  line.

## Structure (`plugin/lib/math/indicators/structure.py`)

- `breakout` (lookback=20) - close above/below the prior lookback
  window's high/low.
- `support_resistance` (lookback=20) - the window's high/low extremes.
- `candlestick_pattern` (doji_body_to_range_max=0.1,
  hammer_wick_to_body_min=2.0, hammer_opposite_wick_to_body_max=0.3) -
  checks the last two bars, in order: bullish engulfing, bearish
  engulfing, doji, hammer, shooting star.
- `gap` - today's open versus yesterday's close.
- `fifty_two_week_range_position` (lookback_bars=252) - percent position
  within the window's high/low range. The 252-bar default approximates a
  year of daily bars; pass a different `lookback_bars` for a different
  window, it is not hardcoded to exactly 252 calendar days.
- `pivot_points` - classic floor-trader pivot, R1-R3/S1-S3, from the
  prior completed bar's high/low/close.

## Cross-sectional (`plugin/lib/math/indicators/cross_sectional.py`)

Each of these takes two bar series, aligned index-for-index by the
caller - `technical-screen`'s script fetches both symbols over the same
date range before calling in.

- `relative_strength` (period=20) - ratio of the symbol's period return
  to a benchmark's.
- `correlation` (period=20) - Pearson correlation of returns.
- `beta` (period=60) - regression beta of the symbol's returns against a
  benchmark's.
- `pairs_spread` (lookback=60, hedge_ratio=1.0) - log-price spread and
  its z-score, for a pairs setup.

## Position sizing (`plugin/lib/math/position_sizing.py`)

- `suggest_stop_distance` (lookback=10) - entry price minus the lowest
  low of the last `lookback` bars.
- `suggest_position_size` - `floor(capital * risk_per_trade_pct / 100 /
  stop_distance)`.
- `suggest_take_profit` (reward_risk_ratio=2.0) - entry price plus the
  stop distance times the ratio.

None of these functions decide whether to take a trade. scan-market's own judgment, reading the news verdict and whichever technical readings it chose to check, makes that call.
