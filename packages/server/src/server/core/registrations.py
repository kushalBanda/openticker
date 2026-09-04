from importlib import import_module

# strategy.strategies and ingest.adapters are both deliberately empty
# __init__.py's, so nothing self-registers until imported.
_MODULES = (
    "ingest.adapters.groww.adapter",
    "ingest.adapters.kite.adapter",
    "strategy.strategies.sma_crossover.strategy",
)


def register_all() -> None:
    for module in _MODULES:
        import_module(module)
