from pathlib import Path

import pytest
from data_engine.core.provider_routes import load_provider_routes


def test_load_provider_routes_reads_symbol_to_provider(tmp_path: Path) -> None:
    config_file = tmp_path / "providers.yaml"
    config_file.write_text("RELIANCE: kite\nAAPL: groww\n")

    routes = load_provider_routes(config_file)

    assert routes == {"RELIANCE": "kite", "AAPL": "groww"}


def test_load_provider_routes_empty_file_returns_empty_dict(tmp_path: Path) -> None:
    config_file = tmp_path / "providers.yaml"
    config_file.write_text("")

    assert load_provider_routes(config_file) == {}


def test_load_provider_routes_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "providers.yaml"
    config_file.write_text("- kite\n- groww\n")

    with pytest.raises(TypeError, match="expected a mapping"):
        load_provider_routes(config_file)


def test_load_provider_routes_real_shipped_config() -> None:
    real_config = Path(__file__).resolve().parents[1] / "config" / "providers.yaml"
    routes = load_provider_routes(real_config)

    assert routes["RELIANCE"] == "kite"
    assert len(routes) >= 1
