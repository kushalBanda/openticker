# CLAUDE.md — packages/quant

This file gives guidance for work inside `packages/quant`. Read the root `/CLAUDE.md` first for workspace-wide rules.

## What this package does

`quant` is the Quant Research Layer: signal generation, forecast scaling, and position sizing. It depends on `ingest` for `Bar` data, but nothing in `strategy` or `execution` depends back on `quant`'s internals beyond its public signal/sizer interfaces.

## Commands

Run these from the repo root, not from inside `packages/quant`.

- Run all tests for this package: `uv run pytest packages/quant/tests`
- Run a single test: `uv run pytest packages/quant/tests/core/test_sizer.py::test_name`
- Type check: `uv run mypy packages/quant`
- Lint: `uv run ruff check packages/quant`

## Architecture

- `core/interfaces.py` defines `Signal` (Protocol) and two frozen dataclasses: `RawSignal` (a signal's raw output value at a point in time) and `Forecast` (a `RawSignal` after scaling). A signal produces a `RawSignal`; scaling turns that into a `Forecast`.
- `core/registry.py` holds a name-to-class registry for signals, the same self-registration pattern used in `ingest` and `strategy`. Signals register with `@register_signal("name")`. Use `SignalFactory` to build a signal instance by name rather than importing signal classes directly.
- `core/sizer.py` converts a `Forecast` into a position size.
- `features/` holds reusable numeric building blocks (`statistics.py`, `technicals.py`, `econometrics.py`) that signals compute from bar data. Put shared math here, not duplicated inside individual signals. Every function here takes and returns a `pandas.Series` indexed by timestamp (`quant.core.series`'s `bar_closes_to_series`/`bar_volumes_to_series` builds that Series from a `list[Bar]`), matching gs-quant's own shape (see `docs/features/gs-quant-integration-ideas.md`), ported formula-by-formula from `docs/resources/gs-quant/gs_quant/timeseries/{statistics,technicals,econometrics}.py`, no GS Marquee/network dependency. `statistics.py` holds `total_return`, `annualized_return`, `sharpe_ratio`, `max_drawdown`, `exponential_std`, and the shared `annualization_factor` helper: `annualized_return`/`sharpe_ratio` derive the annualization factor from a Series' `DatetimeIndex` spacing (Actual/365.25 real elapsed calendar time, not an assumed bar cadence), `sharpe_ratio` uses sample stdev (N-1) and an observation-frequency-bucketed annualization factor and is ×100 scaled, and both accept an optional `risk_free_rate` (Actual/360 excess-return treatment — gs-quant's own currency-keyed risk-free curve requires GS Marquee, deliberately not ported). `technicals.py` holds `moving_average`, `bollinger_bands`, `smoothed_moving_average` (Wilder RMA), `relative_strength_index` (true Wilder RSI — the signal `RsiSignal` uses), `exponential_moving_average`, `macd`, `exponential_volatility`, `exponential_spread_volatility`. `econometrics.py` holds `returns`, `prices`, `index_normalize`, `change`, `annualize`, `volatility`, `correlation`, `beta`. None of these implement gs-quant's `Window`/ramp-up mechanism yet (backlog item, see the doc) — a plain `window: int | None` computes over the full series when `None`.
- `signals/<name>/signal.py` holds one signal implementation per subpackage (e.g. `signals/rsi/`, `signals/sma/`). Each self-registers via `core/registry.py`.
- `storage/signal_store.py` persists computed signals/forecasts, parallel in role to `ingest`'s `duckdb_store.py`.

## Adding a new signal

1. Create `signals/<name>/signal.py`, implement the `Signal` protocol from `core/interfaces.py`.
2. Decorate the class with `@register_signal("<name>")`.
3. Reuse `features/` for any rolling/statistical computation rather than reimplementing it inline.
