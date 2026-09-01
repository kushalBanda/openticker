import pytest
from data_engine.core.constants import PROVIDER_GROWW, PROVIDER_KITE
from data_engine.core.exceptions import DataUnavailableError
from data_engine.core.registry import (
    AdapterFactory,
    get_adapter_class,
    register_adapter,
)


class DummyAdapter:
    def __init__(self, api_key: str = "x") -> None:
        self.api_key = api_key


def test_register_and_create_adapter() -> None:
    register_adapter("dummy")(DummyAdapter)
    instance = AdapterFactory.create("dummy", {"api_key": "abc"})
    assert isinstance(instance, DummyAdapter)
    assert instance.api_key == "abc"


def test_unknown_provider_raises() -> None:
    with pytest.raises(DataUnavailableError):
        get_adapter_class("unknown-provider")


def test_kite_and_groww_register_under_constants_names() -> None:
    import data_engine.adapters.groww.adapter
    import data_engine.adapters.kite.adapter

    assert get_adapter_class(PROVIDER_KITE).__name__ == "KiteAdapter"
    assert get_adapter_class(PROVIDER_GROWW).__name__ == "GrowwAdapter"
