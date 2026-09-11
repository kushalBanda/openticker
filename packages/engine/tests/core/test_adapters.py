from engine.core.adapters import ensure_adapters_registered
from ingest.core.registry import get_adapter_class


def test_ensure_adapters_registered_registers_kite() -> None:
    ensure_adapters_registered()
    assert get_adapter_class("kite") is not None


def test_ensure_adapters_registered_is_idempotent() -> None:
    ensure_adapters_registered()
    ensure_adapters_registered()  # must not raise on second call
    assert get_adapter_class("kite") is not None
