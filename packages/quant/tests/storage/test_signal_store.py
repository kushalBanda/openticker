from datetime import UTC, datetime
from pathlib import Path

from quant.core.interfaces import Forecast, RawSignal
from quant.storage.signal_store import SignalStore


def _raw(value: float = 42.0, ts: datetime = datetime(2026, 1, 1, tzinfo=UTC)) -> RawSignal:
    return RawSignal(symbol="RELIANCE", interval="1d", ts=ts, name="rsi", value=value)


def _forecast(
    scaled_value: float = 8.0, ts: datetime = datetime(2026, 1, 1, tzinfo=UTC)
) -> Forecast:
    return Forecast(
        symbol="RELIANCE", interval="1d", ts=ts, name="rsi", scaled_value=scaled_value
    )


def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    store = SignalStore(db_path=tmp_path / "test.duckdb")
    store.write_signal(_raw())
    store.ensure_schema()
    result = store.query_signals(
        "RELIANCE",
        "1d",
        "rsi",
        datetime(2025, 12, 31, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert len(result) == 1


def test_write_and_query_signals_round_trip(tmp_path: Path) -> None:
    store = SignalStore(db_path=tmp_path / "test.duckdb")
    store.write_signal(_raw(value=71.5))
    result = store.query_signals(
        "RELIANCE",
        "1d",
        "rsi",
        datetime(2025, 12, 31, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert len(result) == 1
    assert result[0].value == 71.5
    assert result[0].symbol == "RELIANCE"
    assert result[0].name == "rsi"


def test_write_and_query_forecasts_round_trip(tmp_path: Path) -> None:
    store = SignalStore(db_path=tmp_path / "test.duckdb")
    store.write_forecast(_forecast(scaled_value=17.2))
    result = store.query_forecasts(
        "RELIANCE",
        "1d",
        "rsi",
        datetime(2025, 12, 31, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert len(result) == 1
    assert result[0].scaled_value == 17.2


def test_write_signal_upserts_on_symbol_interval_ts_name(tmp_path: Path) -> None:
    store = SignalStore(db_path=tmp_path / "test.duckdb")
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    store.write_signal(_raw(value=10.0, ts=ts))
    store.write_signal(_raw(value=99.0, ts=ts))
    result = store.query_signals(
        "RELIANCE",
        "1d",
        "rsi",
        datetime(2025, 12, 31, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert len(result) == 1
    assert result[0].value == 99.0


def test_write_forecast_upserts_on_symbol_interval_ts_name(tmp_path: Path) -> None:
    store = SignalStore(db_path=tmp_path / "test.duckdb")
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    store.write_forecast(_forecast(scaled_value=5.0, ts=ts))
    store.write_forecast(_forecast(scaled_value=-5.0, ts=ts))
    result = store.query_forecasts(
        "RELIANCE",
        "1d",
        "rsi",
        datetime(2025, 12, 31, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert len(result) == 1
    assert result[0].scaled_value == -5.0
