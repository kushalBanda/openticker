from datetime import UTC, datetime

from data_engine.adapters.groww.mapper import map_candle_to_bar, map_tick


def test_map_candle_to_bar_matches_groww_shape() -> None:
    raw = [1735718400, 100.5, 105.0, 99.0, 104.25, 12345]

    bar = map_candle_to_bar(raw, symbol="RELIANCE", interval="1d")

    assert bar.symbol == "RELIANCE"
    assert bar.interval == "1d"
    assert bar.ts == datetime.fromtimestamp(1735718400, tz=UTC)
    assert bar.open == 100.5
    assert bar.high == 105.0
    assert bar.low == 99.0
    assert bar.close == 104.25
    assert bar.volume == 12345
    assert bar.provider == "groww"


def test_map_tick_matches_groww_proto_shape() -> None:
    raw = {"ltp": 4084.0, "volume": 12510, "tsInMillis": 1735718400000}

    tick = map_tick(raw, symbol="RELIANCE")

    assert tick.symbol == "RELIANCE"
    assert tick.price == 4084.0
    assert tick.volume == 12510
    assert tick.ts == datetime.fromtimestamp(1735718400, tz=UTC)
    assert tick.provider == "groww"


def test_map_tick_defaults_volume_and_ts_when_missing() -> None:
    raw = {"ltp": 100.0}

    tick = map_tick(raw, symbol="RELIANCE")

    assert tick.volume == 0
    assert tick.ts.tzinfo == UTC
