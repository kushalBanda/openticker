# CLAUDE.md — plugin/lib

This file gives guidance for work inside `plugin/lib`. Read the root `/CLAUDE.md` first for repo-wide rules.

## What this holds

The only shared code in the repo. Everything here exists to avoid duplicating deterministic math or I/O mechanics across the 4 skill scripts that call into it (`connect-adapter`, `fetch-bars`, `evaluate-signal`, `run-backtest`). Nothing here is a service, a package with its own registry, or a framework - it is flat modules, imported directly by name.

## The mechanics/math split

- `mechanics/` is I/O: things that talk to a network, a filesystem, or a clock. Kite OAuth exchange and historical fetch (`kite.py`), the DuckDB bars store (`store.py`), the credential store (`state.py`), the `Bar` dataclass (`models.py`).
- `math/` is pure computation: given the same inputs, always the same output, no I/O. Indicators, signal evaluation, cost models, position sizing, portfolio/ledger accounting, the backtest loop, and all 5 strategies.

A new file goes in whichever side matches what it actually does. If a function needs to be told to do a network call to compute right, it is mechanics; if it only needs numbers, it is math.

## Hard constraint

**No `Protocol`, no `@register_*` decorator, no `*Factory`, no registry dict.** This directory replaced four Python packages that had exactly that pattern (`ingest`/`quant`/`strategy`/`engine`, each with a `core/registry.py`). The decision to remove it was deliberate (see `docs/superpowers/specs/2026-09-12-openclaw-flat-scripts-design.md`), not an oversight to "fix" by adding one back. Dispatch-by-name (which signal, which strategy) belongs in the *skill script* that needs it, as a plain `dict[str, Callable]` literal - not in `plugin/lib`.

Where a `Protocol` used to exist purely for duck-typing (e.g. `Trigger`/`Action` in the old `strategy.core.trigger`/`action`), the concrete classes/functions survive but the `Protocol` declaration does not - Python does not need it to duck-type, and it added a layer of indirection with no dispatch behind it.

## Adding to `math/`

1. Add the function or class to the most specific existing module (`indicators.py` for a new signal, `strategies/` for a new strategy, a new module if the math doesn't fit anywhere existing).
2. Write its test in `plugin/lib/tests/math/` (or `tests/mechanics/` for I/O), mirroring the module path.
3. Wire it into the one skill script that needs it, as a new dict entry - not a new class hierarchy.

## Numeric-correctness discipline

Every function ported from the old packages was ported to keep bit-for-bit identical behavior - same formula, same edge cases, same constants. If you are porting or changing math here, verify against a known-good fixture (a hand-computed value, or a value from the deleted packages' own tests, recoverable from git history before the deletion commit) rather than asserting by inspection. This is arithmetic a real backtest's result depends on, not a judgment call a skill can safely approximate.
