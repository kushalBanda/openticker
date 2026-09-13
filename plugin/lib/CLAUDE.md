# CLAUDE.md — plugin/lib

This file gives guidance for work inside `plugin/lib`. Read the root `/CLAUDE.md` first for repo-wide rules.

## What this holds

The only shared code in the repo. Everything here exists to avoid duplicating deterministic math or I/O mechanics across the skill scripts that call into it (`connect-adapter`, `fetch-bars`, `research`, `technical-screen`, `position-sizing`; `scan-market` calls the other skills, not `plugin/lib` directly, so it isn't a `plugin/lib` caller itself). Nothing here is a service, a package with its own registry, or a framework - it is flat modules, imported directly by name.

## The mechanics/math split

- `mechanics/` is I/O: things that talk to a network, a filesystem, or a clock. Kite OAuth exchange and historical fetch (`kite.py`), the DuckDB bars store (`store.py`), the credential store (`state.py`), the `Bar` dataclass (`models.py`), NSE index-constituent fetch with a local cache (`nse_index.py`).
- `math/` is pure computation: given the same inputs, always the same output, no I/O. The `indicators/` package (`trend.py`/`momentum.py`/`volatility.py`/`volume.py` wrap `ta`; `structure.py`/`cross_sectional.py` are hand-rolled, since `ta` has no equivalent for either) plus `position_sizing.py`.

Before hand-rolling a new indicator, check whether `ta` (`https://github.com/bukosabino/ta`, already a dependency) already has it - this repo adopted `ta` specifically to avoid re-deriving textbook technical-analysis formulas by hand.

A new file goes in whichever side matches what it actually does. If a function needs to be told to do a network call to compute right, it is mechanics; if it only needs numbers, it is math.

## Hard constraint

**No `Protocol`, no `@register_*` decorator, no `*Factory`, no registry dict.** This directory replaced four Python packages that had exactly that pattern (`ingest`/`quant`/`strategy`/`engine`, each with a `core/registry.py`). The decision to remove it was deliberate (see `docs/superpowers/specs/2026-09-12-openclaw-flat-scripts-design.md`), not an oversight to "fix" by adding one back. Dispatch-by-name (which signal, which strategy) belongs in the *skill script* that needs it, as a plain `dict[str, Callable]` literal - not in `plugin/lib`.

Where a `Protocol` used to exist purely for duck-typing (e.g. `Trigger`/`Action` in the old `strategy.core.trigger`/`action`), the concrete classes/functions survive but the `Protocol` declaration does not - Python does not need it to duck-type, and it added a layer of indirection with no dispatch behind it.

## Adding to `math/`

1. Add the function to the matching category module in `indicators/` (`trend.py`, `momentum.py`, `volatility.py`, `volume.py` if `ta` has an equivalent; `structure.py` or `cross_sectional.py` if it doesn't), or to `position_sizing.py`.
2. Give every threshold/window a keyword parameter with a default - never close over a fixed value. This is a Global Constraint, not a suggestion.
3. Write its test in `plugin/lib/tests/math/indicators/` (or `tests/mechanics/` for I/O), mirroring the module path.
4. Wire it into `technical-screen`'s script's `_SINGLE_SERIES_INDICATORS` or `_CROSS_SECTIONAL_INDICATORS` dict - not a new class hierarchy.

## Numeric-correctness discipline

Every function ported from the old packages was ported to keep bit-for-bit identical behavior - same formula, same edge cases, same constants. If you are porting or changing math here, verify against a known-good fixture (a hand-computed value, or a value from the deleted packages' own tests, recoverable from git history before the deletion commit) rather than asserting by inspection. This is arithmetic a real backtest's result depends on, not a judgment call a skill can safely approximate.
