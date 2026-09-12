# Quant Platform plugin

Claude Code plugin for the [Quant Platform](https://github.com/kushalBanda/Quant) repo. There is no server and no separate Python package behind it - each skill below runs its own script directly against `plugin/lib`, in-process, no MCP tool layer for this repo's own logic.

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
| `evaluate-signal` | Checking whether a signal (RSI, SMA, ...) predicts a symbol's forward returns. |
| `run-backtest` | Backtesting one of 5 strategies against real historical bars. |

Each skill's `SKILL.md` runs its own `scripts/<name>.py` and turns the JSON it prints into a plain-language answer - the skill file owns all the orchestration and decision-making.

## Agents

| Agent | Purpose |
|---|---|
| `research-agent` | Turns fetched OHLCV bars into a plain-language research report, invoked by the `research` skill. |

## Shared library

`plugin/lib/` is the only shared code, split into `mechanics/` (Kite auth, historical fetch, DuckDB bars store) and `math/` (indicators, signal evaluation, cost models, the backtest loop, all 5 strategies). No registry, no `Protocol`, no factory - see `plugin/lib/CLAUDE.md` for how to extend it.

## References

`references/install.md`, `references/kite-app-setup.md`, `references/strategies.md`, `references/quant-signals.md`, `references/cost-models.md` - background Claude reads when a skill needs it, not run directly.
