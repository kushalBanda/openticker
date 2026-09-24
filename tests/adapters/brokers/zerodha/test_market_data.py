from datetime import UTC, date, datetime
from types import TracebackType
from typing import Any, Self

import httpx
import pytest

from openticker.adapters.brokers.zerodha import market_data
from openticker.adapters.brokers.zerodha.adapter import ZerodhaAdapter
from openticker.ports.errors import BrokerRateLimitError
from tests.fixtures.fake_broker import FAKE_INSTRUMENT


class _FakeClient:
    """Stands in for httpx.Client; answers each GET with the next queued response."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.requests: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def __call__(self, base_url: str, timeout: float) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        pass

    def get(self, path: str, params: dict[str, str], headers: dict[str, str]) -> httpx.Response:
        self.requests.append((path, params, headers))
        return self._responses.pop(0)


def _ok(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"status": "success", "data": data})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda seconds: None)


def _install(monkeypatch: pytest.MonkeyPatch, responses: list[httpx.Response]) -> _FakeClient:
    client = _FakeClient(responses)
    monkeypatch.setattr(httpx, "Client", client)
    return client


def test_fetch_quote_maps_price_and_converts_ist_trade_time_to_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _install(
        monkeypatch,
        [_ok({"NSE:RELIANCE": {"last_price": 1374.6, "last_trade_time": "2026-09-18 15:29:59"}})],
    )

    quote = market_data.fetch_quote("key", "token", FAKE_INSTRUMENT)

    assert quote.last_price == 1374.6
    assert quote.as_of == datetime(2026, 9, 18, 9, 59, 59, tzinfo=UTC)
    path, params, headers = client.requests[0]
    assert (path, params) == ("/quote", {"i": "NSE:RELIANCE"})
    assert headers["Authorization"] == "token key:token"


def test_fetch_quote_falls_back_to_timestamp_for_indices(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        [_ok({"NSE:RELIANCE": {"last_price": 25000.0, "timestamp": "2026-09-18 15:30:00"}})],
    )

    quote = market_data.fetch_quote("key", "token", FAKE_INSTRUMENT)

    assert quote.as_of == datetime(2026, 9, 18, 10, 0, tzinfo=UTC)


def test_expired_session_raises_session_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [httpx.Response(403, json={"error_type": "TokenException"})])

    with pytest.raises(market_data.KiteSessionError):
        market_data.fetch_quote("key", "token", FAKE_INSTRUMENT)


def test_rate_limit_raises_a_rate_limit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [httpx.Response(429, json={"error_type": "NetworkException"})])

    with pytest.raises(BrokerRateLimitError, match="429"):
        market_data.fetch_quotes("key", "token", [FAKE_INSTRUMENT])


def test_fetch_candles_converts_to_utc_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        [_ok({"candles": [["2026-09-18T00:00:00+0530", 1370, 1380.5, 1365, 1374.6, 4567890]]})],
    )

    bars = market_data.fetch_candles(
        "key", "token", FAKE_INSTRUMENT, "day", date(2026, 9, 18), date(2026, 9, 18)
    )

    assert len(bars) == 1
    assert bars[0].timestamp == datetime(2026, 9, 17, 18, 30, tzinfo=UTC)
    assert (bars[0].open, bars[0].close, bars[0].volume) == (1370.0, 1374.6, 4567890)


def test_fetch_candles_splits_long_ranges_without_gaps_or_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _install(monkeypatch, [_ok({"candles": []}), _ok({"candles": []})])

    market_data.fetch_candles(
        "key", "token", FAKE_INSTRUMENT, "minute", date(2026, 1, 1), date(2026, 3, 2)
    )

    ranges = [(params["from"], params["to"]) for _, params, _ in client.requests]
    assert ranges == [
        ("2026-01-01 00:00:00", "2026-03-01 23:59:59"),  # 60 days, minute's limit
        ("2026-03-02 00:00:00", "2026-03-02 23:59:59"),
    ]


def test_fetch_candles_failed_chunk_raises_instead_of_returning_partial_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        [
            _ok({"candles": [["2026-01-01T09:15:00+0530", 1, 1, 1, 1, 1]]}),
            httpx.Response(429, text="Too many requests"),
        ],
    )

    with pytest.raises(market_data.KiteApiError):
        market_data.fetch_candles(
            "key", "token", FAKE_INSTRUMENT, "minute", date(2026, 1, 1), date(2026, 3, 2)
        )


def test_fetch_candles_rejects_unknown_interval() -> None:
    with pytest.raises(ValueError, match="unknown interval"):
        market_data.fetch_candles(
            "key", "token", FAKE_INSTRUMENT, "2hour", date(2026, 1, 1), date(2026, 1, 2)
        )


def test_adapter_without_session_raises_before_any_http_call() -> None:
    adapter = ZerodhaAdapter(api_key="key", api_secret="secret", access_token=None)

    with pytest.raises(market_data.KiteSessionError, match="not connected"):
        adapter.get_quote(FAKE_INSTRUMENT)


def test_fetch_quotes_batches_and_skips_instruments_kite_did_not_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    instruments = [
        replace(FAKE_INSTRUMENT, symbol=f"S{n}", broker_symbol=f"S{n}") for n in range(501)
    ]
    first = {
        f"NSE:S{n}": {"last_price": 10.0, "oi": 1500, "timestamp": "2026-09-18 15:30:00"}
        for n in range(500)
        if n != 7
    }
    client = _install(
        monkeypatch,
        [_ok(first), _ok({"NSE:S500": {"last_price": 11.0, "timestamp": "2026-09-18 15:30:00"}})],
    )

    quotes = market_data.fetch_quotes("key", "token", instruments)

    assert len(client.requests) == 2
    assert len(client.requests[0][1]) == market_data.MAX_QUOTES_PER_REQUEST
    assert len(quotes) == 500
    assert "S7" not in {quote.instrument.symbol for quote in quotes}
    assert quotes[0].open_interest == 1500
    assert quotes[-1].open_interest is None


def test_fetch_quote_carries_the_day_range(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        [
            _ok(
                {
                    "NSE:RELIANCE": {
                        "last_price": 1374.6,
                        "timestamp": "2026-09-18 15:30:00",
                        "ohlc": {"open": 1360.0, "high": 1380.0, "low": 1355.5, "close": 1358.0},
                    }
                }
            )
        ],
    )

    quote = market_data.fetch_quote("key", "token", FAKE_INSTRUMENT)

    assert (quote.day_low, quote.day_high) == (1355.5, 1380.0)


def test_fetch_quote_carries_the_best_bid_and_ask_and_the_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        [
            _ok(
                {
                    "NSE:RELIANCE": {
                        "last_price": 1374.6,
                        "timestamp": "2026-09-18 15:30:00",
                        "volume": 5_120_334,
                        "ohlc": {"open": 1360.0, "high": 1380.0, "low": 1355.5, "close": 1358.0},
                        "depth": {
                            "buy": [{"price": 1374.5, "quantity": 12, "orders": 3}],
                            "sell": [{"price": 0, "quantity": 0, "orders": 0}],
                        },
                    }
                }
            )
        ],
    )

    quote = market_data.fetch_quote("key", "token", FAKE_INSTRUMENT)

    assert (quote.bid, quote.ask) == (1374.5, None)  # Kite pads an empty side with price 0
    assert (quote.bid_quantity, quote.ask_quantity) == (12, None)
    assert (quote.open, quote.close, quote.volume) == (1360.0, 1358.0, 5_120_334)


def test_fetch_depth_drops_empty_levels_and_keeps_the_whole_book_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = {"price": 0, "quantity": 0, "orders": 0}
    client = _install(
        monkeypatch,
        [
            _ok(
                {
                    "NSE:RELIANCE": {
                        "last_price": 1374.6,
                        "last_quantity": 7,
                        "last_trade_time": "2026-09-18 15:29:59",
                        "buy_quantity": 50_000,
                        "sell_quantity": 42_000,
                        "volume": 5_120_334,
                        "ohlc": {"open": 1360.0, "high": 1380.0, "low": 1355.5, "close": 1358.0},
                        "depth": {
                            "buy": [
                                {"price": 1374.5, "quantity": 12, "orders": 3},
                                {"price": 1374.4, "quantity": 30, "orders": 5},
                                empty,
                                empty,
                                empty,
                            ],
                            "sell": [{"price": 1374.7, "quantity": 9, "orders": 1}] + [empty] * 4,
                        },
                    }
                }
            )
        ],
    )

    depth = market_data.fetch_depth("key", "token", FAKE_INSTRUMENT)

    assert [(level.price, level.quantity, level.orders) for level in depth.bids] == [
        (1374.5, 12, 3),
        (1374.4, 30, 5),
    ]
    assert [level.price for level in depth.asks] == [1374.7]
    assert (depth.total_buy_quantity, depth.total_sell_quantity) == (50_000, 42_000)
    assert (depth.last_price, depth.last_quantity, depth.close, depth.volume) == (
        1374.6,
        7,
        1358.0,
        5_120_334,
    )
    assert depth.open_interest is None  # equities carry no OI
    assert client.requests[0][:2] == ("/quote", {"i": "NSE:RELIANCE"})


def test_depth_reads_five_levels_a_side_and_quote_reads_the_same_best(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    side = [{"price": 100.0 - i, "quantity": i + 1, "orders": 1} for i in range(7)]
    payload = {"NSE:RELIANCE": {"last_price": 100.0, "depth": {"buy": side, "sell": []}}}
    _install(monkeypatch, [_ok(payload), _ok(payload)])

    depth = market_data.fetch_depth("key", "token", FAKE_INSTRUMENT)
    quote = market_data.fetch_quote("key", "token", FAKE_INSTRUMENT)

    assert [level.price for level in depth.bids] == [100.0, 99.0, 98.0, 97.0, 96.0]
    assert depth.asks == ()
    assert (quote.bid, quote.bid_quantity) == (depth.bids[0].price, depth.bids[0].quantity)
    assert (quote.ask, quote.ask_quantity) == (None, None)
