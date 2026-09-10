# Quant Platform plugin

Claude Code plugin for the [Quant Platform](https://github.com/kushalBanda/Quant) repo: connect a broker/data adapter and run market data, backtest, and research skills directly against `packages/ingest`, `packages/quant`, and `packages/strategy` - in-process, no server.

## Install

```
claude plugin marketplace add ./.claude-plugin/marketplace.json
claude plugin install quant-platform@quant-platform-marketplace
```

See `references/install.md` for the full one-time setup (workspace trust, Kite app registration).

## Skills

| Skill | Use when |
|---|---|
| `connect-adapter` | Connecting a broker/data provider (Kite Connect; Groww deferred). |
| `fetch-bars` | A plain historical price/OHLCV data request. |
| `research` | A written research report on a symbol (trend, volatility, outside context). |
| `run-backtest` | Backtesting a registered strategy against real historical bars. |

## Agents

| Agent | Purpose |
|---|---|
| `research-agent` | Turns fetched OHLCV bars into a plain-language research report, invoked by the `research` skill. |

## References

`references/install.md`, `references/kite-app-setup.md`, `references/strategies.md`, `references/quant-signals.md` - background Claude reads when a skill needs it, not run directly.

## Scripts

`scripts/*.py` are called by skills via `uv run python plugin/scripts/<name>.py ...` from the repo root - never invoked by the user directly. `state.py` (local credential store) and `adapters.py`/`strategies.py` (self-registration helpers) are shared infrastructure; `data.py` is the shared bar-fetch helper `fetch_bars.py` and `run_backtest.py` both use.
