"""The names behind `triggered_by` (ADR 35 in docs/adr): which strategy or
hosted script placed an order, so a row can say "NIFTY short straddle", not
"strategy:3f2a…"."""

from collections.abc import Iterable

from openticker.storage.sqlite import scripts_repo, strategies_repo
from openticker.use_cases.api_keys import SCRIPT_SCOPE_PREFIX

_STRATEGY = "strategy:"


def placer_names(triggered_by: Iterable[str]) -> dict[str, str]:
    """Each `strategy:<id>` and `script:<id>` among `triggered_by` whose
    strategy or script still exists, mapped to its name."""
    wanted = set(triggered_by)
    names: dict[str, str] = {}
    if any(t.startswith(_STRATEGY) for t in wanted):
        for strategy in strategies_repo.list_strategies():
            names[f"{_STRATEGY}{strategy.id}"] = strategy.name
    if any(t.startswith(SCRIPT_SCOPE_PREFIX) for t in wanted):
        for script in scripts_repo.list_scripts():
            names[f"{SCRIPT_SCOPE_PREFIX}{script.id}"] = script.name
    return {t: names[t] for t in wanted if t in names}
