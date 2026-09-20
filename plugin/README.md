# Quant Platform plugin

Claude Code plugin for the [Quant Platform](https://github.com/kushalBanda/Quant) repo. There is no server and no separate Python package behind it - each skill below runs its own script directly against `plugin/lib`, in-process, no MCP tool layer for this repo's own logic.

## Install

```
claude plugin marketplace add ./.claude-plugin/marketplace.json
claude plugin install quant-platform@quant-platform-marketplace
```

See `references/kite-app-setup.md` for Kite app registration.

## Skills

| Skill | Use when |
|---|---|
| `connect-adapter` | Connecting a broker/data provider (Kite Connect; Groww deferred). |
| `fetch-bars` | A plain historical price/OHLCV data request. |

Each skill's `SKILL.md` runs its own `scripts/<name>.py` and turns the JSON it prints into a plain-language answer - the skill file owns all the orchestration and decision-making.

## Shared library

`plugin/lib/` is the only shared code: `mechanics/` (Kite auth, historical fetch, DuckDB bars store). No registry, no `Protocol`, no factory - see `plugin/lib/CLAUDE.md` for how to extend it.

## References

`references/kite-app-setup.md` - background Claude reads when a skill needs it, not run directly.
