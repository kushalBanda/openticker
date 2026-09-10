"""Registers ingest's provider adapters for AdapterFactory.create(...).

`ingest.adapters.*` packages are deliberately empty __init__.py's - an
adapter only self-registers (via @register_adapter) when its concrete
module is actually imported. packages/server has its own version of this
(server/core/registrations.py); the plugin needs the same step since it
does not import packages/server.
"""

from importlib import import_module

_ADAPTER_MODULES = (
    "ingest.adapters.kite.adapter",
    "ingest.adapters.groww.adapter",  # deferred (ticket 04), harmless to import now
)

_registered = False


def ensure_adapters_registered() -> None:
    global _registered
    if _registered:
        return
    for module in _ADAPTER_MODULES:
        import_module(module)
    _registered = True
