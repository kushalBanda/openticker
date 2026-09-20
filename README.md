# Quant

Quant pulls historical bars from Kite Connect and stores them locally in DuckDB. No server, no framework - just two CLI scripts and a small shared library.

## What it does today

- **Connect a broker** - log in to Kite so data can flow: `uv run python scripts/connect_adapter.py`
- **Fetch bars** - pull historical OHLCV data for a symbol: `uv run python scripts/fetch_bars.py --symbol RELIANCE --days 365`

## How it works

```
 scripts/connect_adapter.py, scripts/fetch_bars.py   (thin CLI entry points)
      │  call into
      ▼
 lib/mechanics   → Kite auth, historical fetch, DuckDB bars store
      │
      ▼
 One JSON object printed to stdout
```

There is no registry, no `Protocol`, no factory pattern anywhere in `lib`.

## Get started

```bash
uv sync                # install dependencies
uv run pytest          # confirm the mechanics work
uv run python scripts/connect_adapter.py
uv run python scripts/fetch_bars.py --symbol RELIANCE --days 365
```

See `references/kite-app-setup.md` for registering a Kite Connect app first.

## Stack

Quant is Python only, on Python 3.13, run as flat scripts via `uv` - no build step, no installed package. `mypy --strict` and `ruff` must pass clean before any change is considered done.

## Data sources

Kite Connect is wired in today, for Indian markets.

## License

MIT. See `LICENSE`.
