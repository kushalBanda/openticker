# Quant

Quant is a self-hosted trading bot platform. You talk to it through Claude Code. You ask for data, a research report, a technical reading, or a full market scan, in plain language, and it runs on real market data.

Quant pulls bars from Kite Connect, computes technical indicators, and proposes stop/target/size for a candidate trade. There is no separate server and no multi-package Python backend - the Claude Code plugin in `plugin/` is the entire product, built OpenClaw-style: a thin script per skill does the mechanics, the skill's own instructions do all the orchestration, and one small shared library holds the deterministic math.

## What it does today

- **Fetch bars** - pull historical OHLCV data for a symbol, for example "fetch me Reliance data for the last year".
- **Research** - get a plain language report on trend, volatility, and notable levels, with optional web and news context.
- **Connect a broker** - log in to Kite so live data can flow.
- **Scan the market** - find trade candidates from the day's news, verify them, check their chart, and propose a position, with no symbol named up front.
- **Check any technical indicator** - trend, momentum, volatility, volume, structure, or cross-sectional, on any symbol, with any parameters you name.

All computation is deterministic Python. Claude Code is the interactive layer, not the engine. It never invents a bar or a fill.

## How it works

```
 You, in Claude Code
      │  "scan the market for setups"
      ▼
 A skill's SKILL.md (fetch-bars, research, connect-adapter, scan-market, technical-screen, position-sizing)
      │  runs
      ▼
 That skill's own script (plugin/skills/<name>/scripts/<name>.py) - scan-market has none, it's pure orchestration
      │  calls into
      ▼
 plugin/lib/mechanics  → Kite auth, historical fetch, DuckDB bars store, NSE index constituents
 plugin/lib/math        → the indicators/ package, position sizing
      │
      ▼
 One JSON result, turned into a plain-language report back to you
```

There is no registry, no `Protocol`, no factory pattern anywhere in `plugin/lib` - a new technical indicator is one new function and one new dict entry in the skill script that uses it, nothing more.

## Get started

```bash
uv sync                # install dependencies
uv run pytest          # confirm the math and mechanics work
```

Then, inside Claude Code, install the plugin once:

```
/plugin install quant-platform@quant-platform-marketplace
```

After that, just ask in plain language:

- "Connect my Kite account"
- "Fetch me TCS data for the last 6 months"
- "Give me a research report on Reliance"
- "Scan the market for setups"
- "What's the RSI and 200-EMA on Reliance?"

## Stack

Quant is Python only, on Python 3.13, run as flat scripts via `uv` - no build step, no installed package. `mypy --strict` and `ruff` must pass clean before any change is considered done.

No week or time estimates appear anywhere in this repo. Work is sequenced by dependency, not by a timeline.

## Data sources

Kite Connect is wired in today, for Indian markets. Groww is planned but not yet built (see `plugin/skills/connect-adapter/SKILL.md`).

## License

MIT. See `LICENSE`.
