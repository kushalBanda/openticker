from datetime import UTC, date, datetime
from types import TracebackType
from typing import Any, Self

import httpx
import pytest

from openticker.adapters.brokers.zerodha import market_data
from openticker.adapters.brokers.zerodha.adapter import ZerodhaAdapter
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
