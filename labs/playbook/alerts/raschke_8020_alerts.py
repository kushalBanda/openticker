"""Linda Raschke's 80-20 reversal alerts for raschke-8020-reversal (stg_287a72403550).

From Street Smarts (Connors and Raschke). Yesterday opened in the top 20%
of its range and closed in the bottom 20%: if today trades at least 0.1%
below yesterday's low and comes back above it, long_entry. Mirror for
shorts. One entry per stock per day; the strategy's 0.8% stop, 1.6%
target and 15:10 exit close it. Runs 09:15-13:30: the reversal is a
morning trade.
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

SYMBOLS = [
    (s, "NSE")
    for s in [
        "TITAN",
        "ASIANPAINT",
        "EICHERMOT",
        "ULTRACEMCO",
        "DRREDDY",
        "HCLTECH",
        "CIPLA",
        "BRITANNIA",
    ]
]
PIERCE = 0.001
LAST_ENTRY = "13:30"
POLL_SECONDS = 10

IST = ZoneInfo("Asia/Kolkata")
BASE = os.environ["OPENTICKER_URL"].rstrip("/")
API = httpx.Client(
    base_url=f"{BASE}/api/v1", headers={"X-API-Key": os.environ["OPENTICKER_API_KEY"]}, timeout=15
)
STATE = Path("state.json")
# The strategy's alert token, kept beside the script and out of its source.
TOKEN = Path("alert_token").read_text().strip()


def now() -> datetime:
    return datetime.now(IST)


def load_state() -> dict:
    today = now().date().isoformat()
    if STATE.exists():
        state = json.loads(STATE.read_text())
        if state.get("date") == today:
            return state
    return {"date": today, "levels": {}, "entered": {}}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state))


def market_open() -> bool:
    status = API.get("/market-status", params={"exchange": "NSE"}).raise_for_status().json()
    return status["exchanges"][0]["is_open"]


def daily_bars(symbol: str, exchange: str, days: int) -> list[dict]:
    """Completed daily bars, oldest first, today excluded."""
    today = now().date()
    bars = (
        API.get(
            "/bars",
            params={
                "broker": "zerodha",
                "symbol": symbol,
                "exchange": exchange,
                "interval": "day",
                "start_date": (today - timedelta(days=days * 2 + 10)).isoformat(),
                "end_date": today.isoformat(),
            },
        )
        .raise_for_status()
        .json()["bars"]
    )
    return [b for b in bars if b["timestamp"][:10] < today.isoformat()][-days:]


def quote(symbol: str, exchange: str) -> dict:
    reply = API.get("/quote", params={"broker": "zerodha", "symbol": symbol, "exchange": exchange})
    return reply.raise_for_status().json()


def alert(action: str, symbol: str, exchange: str) -> None:
    reply = httpx.post(
        f"{BASE}/webhooks/strategies/{TOKEN}",
        json={"action": action, "symbol": symbol, "exchange": exchange},
        timeout=15,
    )
    print(f"{now():%H:%M:%S} {action} {symbol}: {reply.status_code} {reply.text[:200]}", flush=True)


def watch(state: dict, levels_of, trigger, start: str, last_entry: str) -> None:
    """Waits for start, fixes each symbol's levels once, then sends one entry a symbol a day."""
    while now().strftime("%H:%M") < start:
        time.sleep(15)
    for symbol, exchange in SYMBOLS:
        if symbol not in state["levels"]:
            found = levels_of(symbol, exchange)
            if found is None:
                print(f"{symbol}: no setup today.", flush=True)
                continue
            state["levels"][symbol] = found
            print(f"{symbol} levels {found}", flush=True)
    save_state(state)
    exchange_of = dict(SYMBOLS)
    while now().strftime("%H:%M") < last_entry:
        waiting = [s for s in state["levels"] if s in exchange_of and s not in state["entered"]]
        if not waiting:
            print("Every setup entered; done for the day.")
            return
        for symbol in waiting:
            q = quote(symbol, exchange_of[symbol])
            action = trigger(state["levels"][symbol], q)
            if action:
                alert(action, symbol, exchange_of[symbol])
                state["entered"][symbol] = action
                save_state(state)
        time.sleep(POLL_SECONDS)
    print(f"No more entries after {last_entry}.")


def levels_of(symbol: str, exchange: str) -> dict | None:
    bars = daily_bars(symbol, exchange, 1)
    if not bars:
        return None
    b = bars[-1]
    span = b["high"] - b["low"]
    if span <= 0:
        return None
    where_open, where_close = (b["open"] - b["low"]) / span, (b["close"] - b["low"]) / span
    if where_open >= 0.8 and where_close <= 0.2:
        return {"side": "long", "level": b["low"], "pierced": False}
    if where_open <= 0.2 and where_close >= 0.8:
        return {"side": "short", "level": b["high"], "pierced": False}
    return None


def trigger(levels: dict, q: dict) -> str | None:
    price = q["last_price"]
    if levels["side"] == "long":
        levels["pierced"] = levels["pierced"] or q["low"] <= levels["level"] * (1 - PIERCE)
        return "long_entry" if levels["pierced"] and price > levels["level"] else None
    levels["pierced"] = levels["pierced"] or q["high"] >= levels["level"] * (1 + PIERCE)
    return "short_entry" if levels["pierced"] and price < levels["level"] else None


def main() -> None:
    if not market_open():
        print("NSE closed; nothing to do today.")
        return
    watch(load_state(), levels_of, trigger, "09:20", LAST_ENTRY)


if __name__ == "__main__":
    main()
