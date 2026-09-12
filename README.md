# Quant

Quant is a self-hosted trading bot platform. You talk to it through Claude Code. You ask for data, a research report, a backtest, or — once execution ships — a live or paper trade, in plain language, and it runs on real market data.

Quant pulls bars from Kite Connect and Groww, computes signals and position sizes, and runs those signals through a hand built backtest engine. Order execution (paper, then live) is the current build priority — see `docs/designs/trading-bot-first-pivot.md`. A Claude Code plugin sits on top and exposes this as skills: fetch data, run research, connect a broker, run a backtest.

## What it does today

- **Fetch bars** - pull historical OHLCV data for a symbol, for example "fetch me Reliance data for the last year".
- **Research** - get a plain language report on trend, volatility, and notable levels, with optional web and news context.
- **Connect a broker** - log in to Kite so live data and orders can flow.
- **Run a backtest** - test a strategy, such as a moving average crossover or pairs trading, against real historical bars.

## What's next

Real order execution — a `PaperBroker`, gated by a pre-trade risk pipeline, then `LiveBroker` through Kite. This is not built yet. See `docs/designs/trading-bot-first-pivot.md` for the full design and safety gates.

All computation is deterministic Python. Claude Code is the interactive layer, not the engine. It never invents a bar or a fill.

## How it works

```
 You, in Claude Code
      │  "backtest a moving average crossover on Reliance"
      ▼
 Plugin skills (fetch-bars, research, connect-adapter, run-backtest)
      │  calls into
      ▼
 packages/ingest    → provider adapters (Kite, Groww) → bars in DuckDB
 packages/quant      → signals, forecast scaling, position sizing
 packages/strategy   → bar-by-bar backtest engine, pluggable strategies
      │
      ▼
 Report, chart, or trade log back to you
```

`ingest` fetches and stores bars. `quant` turns bars into signals and position sizes. `strategy` runs those signals through a backtest, bar by bar, and reports results. Each package is Python, typed, and tested on its own.

## Get started

```bash
uv sync                # install dependencies
uv run pytest          # confirm the engine works
```

Then, inside Claude Code, install the plugin once:

```
/plugin install quant-platform@quant-platform-marketplace
```

After that, just ask in plain language:

- "Connect my Kite account"
- "Fetch me TCS data for the last 6 months"
- "Give me a research report on Reliance"
- "Backtest a moving average crossover on Reliance"

## Stack

Quant is Python only, on Python 3.13, managed with uv. `mypy --strict` and `ruff` must pass clean before any change is considered done. This is a deliberate choice. The goal is a real, working platform, not a C++ port or an interview exercise.

No week or time estimates appear anywhere in this repo. Work is sequenced by dependency, not by a timeline.

## Data sources

Kite Connect and Groww are wired in today, for Indian markets. Upstox is planned but not yet built. Adding a new provider does not require touching the core engine.

## License

MIT. See `LICENSE`.
