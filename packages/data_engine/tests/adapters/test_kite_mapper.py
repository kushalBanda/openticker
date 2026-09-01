from datetime import UTC, datetime

from data_engine.adapters.kite.mapper import map_candle_to_bar, map_tick


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


def test_map_tick_matches_kite_ticker_shape() -> None:
    raw = {
        "instrument_token": 128083204,
        "last_price": 4084.0,
        "volume_traded": 12510,
        # naive, matching Kite's real (undocumented timezone) tick shape
        "exchange_timestamp": datetime(2026, 1, 15, 13, 16, 56),
    }

    tick = map_tick(raw, symbol="RELIANCE")

    assert tick.symbol == "RELIANCE"
    assert tick.price == 4084.0
    assert tick.volume == 12510
    assert tick.ts == datetime(2026, 1, 15, 7, 46, 56, tzinfo=UTC)
    assert tick.provider == "kite"


def test_map_tick_falls_back_to_last_trade_time() -> None:
    raw = {
        "instrument_token": 128083204,
        "last_price": 100.0,
        "last_trade_time": datetime(2026, 1, 15, 13, 16, 54),
    }

    tick = map_tick(raw, symbol="RELIANCE")

    assert tick.ts == datetime(2026, 1, 15, 7, 46, 54, tzinfo=UTC)
    assert tick.volume == 0
