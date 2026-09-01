from datetime import UTC, datetime

from data_engine.adapters.kite.mapper import map_candle_to_bar


def test_map_candle_to_bar_matches_kite_shape() -> None:
    raw = ["2017-12-15T09:15:00+0000", 100.5, 105.0, 99.0, 104.25, 12345]

    bar = map_candle_to_bar(raw, symbol="RELIANCE", interval="1d")

    assert bar.symbol == "RELIANCE"
    assert bar.interval == "1d"
    assert bar.ts == datetime(2017, 12, 15, 9, 15, tzinfo=UTC)
    assert bar.open == 100.5
    assert bar.high == 105.0
    assert bar.low == 99.0
    assert bar.close == 104.25
    assert bar.volume == 12345
    assert bar.provider == "kite"


def test_map_candle_to_bar_handles_ist_offset() -> None:
    raw = ["2017-12-15T09:15:00+0530", 100.0, 100.0, 100.0, 100.0, 1]

    bar = map_candle_to_bar(raw, symbol="RELIANCE", interval="1d")

    assert bar.ts == datetime(2017, 12, 15, 3, 45, tzinfo=UTC)
