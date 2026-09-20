# Quant

Quant is a self-hosted trading bot platform. You talk to it through Claude Code. You ask for market data in plain language, and it pulls it from real broker data.

Quant pulls bars from Kite Connect and stores them locally. There is no separate server and no multi-package Python backend - the Claude Code plugin in `plugin/` is the entire product, built OpenClaw-style: a thin script per skill does the mechanics, the skill's own instructions do all the orchestration.

## What it does today

- **Connect a broker** - log in to Kite so data can flow.
- **Fetch bars** - pull historical OHLCV data for a symbol, for example "fetch me Reliance data for the last year".

## How it works

```
 You, in Claude Code
      │  "fetch me Reliance data"
      ▼
 A skill's SKILL.md (connect-adapter, fetch-bars)
      │  runs
      ▼
 That skill's own script (plugin/skills/<name>/scripts/<name>.py)
      │  calls into
      ▼
 plugin/lib/mechanics  → Kite auth, historical fetch, DuckDB bars store
      │
      ▼
 One JSON result, turned into a plain-language report back to you
```

There is no registry, no `Protocol`, no factory pattern anywhere in `plugin/lib`.

## Get started

```bash
uv sync                # install dependencies
uv run pytest          # confirm the mechanics work
```

Then, inside Claude Code, install the plugin once:

```
/plugin install quant-platform@quant-platform-marketplace
```

After that, just ask in plain language:

- "Connect my Kite account"
- "Fetch me TCS data for the last 6 months"

## Stack

Quant is Python only, on Python 3.13, run as flat scripts via `uv` - no build step, no installed package. `mypy --strict` and `ruff` must pass clean before any change is considered done.

No week or time estimates appear anywhere in this repo. Work is sequenced by dependency, not by a timeline.

## Data sources

Kite Connect is wired in today, for Indian markets. Groww is planned but not yet built (see `plugin/skills/connect-adapter/SKILL.md`).

## License

MIT. See `LICENSE`.
