# CLAUDE.md — plugin/lib

This file gives guidance for work inside `plugin/lib`. Read the root `/CLAUDE.md` first for repo-wide rules.

## What this holds

The only shared code in the repo. Everything here exists to avoid duplicating Kite I/O mechanics across the skill scripts that call into it (`connect-adapter`, `fetch-bars`). Nothing here is a service, a package with its own registry, or a framework - it is flat modules, imported directly by name.

## `mechanics/`

I/O: things that talk to a network, a filesystem, or a clock. Kite OAuth exchange and historical fetch (`kite.py`), the DuckDB bars store (`store.py`), the credential store (`state.py`), the `Bar` dataclass (`models.py`), shared exceptions (`exceptions.py`).

## Hard constraint

**No `Protocol`, no `@register_*` decorator, no `*Factory`, no registry dict.** Dispatch-by-name belongs in the *skill script* that needs it, as a plain `dict[str, Callable]` literal - not in `plugin/lib`.
