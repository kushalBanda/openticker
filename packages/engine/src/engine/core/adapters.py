"""Registers ingest's provider adapters for AdapterFactory.create(...).

`ingest.adapters.*` packages are deliberately empty __init__.py's - an
adapter only self-registers (via @register_adapter) when its concrete
module is actually imported. The engine needs this explicit step since
it does not go through any server-side registration module.
"""

from importlib import import_module

_ADAPTER_MODULES = (
    "ingest.adapters.kite.adapter",
    "ingest.adapters.groww.adapter",  # deferred (ticket 04), harmless to import now
)

_registered = False


def ensure_adapters_registered() -> None:
    """Import every adapter module once, triggering its @register_adapter.

    Idempotent - safe to call at the top of every tool that needs
    AdapterFactory.create(...) to know about all providers.
    """
    global _registered
    if _registered:
        return
    for module in _ADAPTER_MODULES:
        import_module(module)
    _registered = True
