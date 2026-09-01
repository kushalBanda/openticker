from datetime import UTC, datetime

from data_engine.adapters.groww.mapper import map_candle_to_bar


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
