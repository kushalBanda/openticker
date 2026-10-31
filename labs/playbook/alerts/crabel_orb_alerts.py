"""Toby Crabel opening range breakout alerts for crabel-orb-index-futures (stg_9f7685a15356).

Stretch = the 10-day average of min(high - open, open - low), Crabel's
measure of how far price wanders from the open before it commits. Above
today's open + stretch: long_entry. Below open - stretch: short_entry.
One entry per future per day; the strategy's stops, trailing stop and
15:10 exit close it. NR4/NR7 days (range the narrowest of 4/7) are logged:
Crabel found the breakout strongest after them. Runs 09:15-14:30.
The futures are the November contracts: roll the legs and SYMBOLS at expiry.
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

SYMBOLS = [("NIFTY23NOV26FUT", "NFO"), ("BANKNIFTY23NOV26FUT", "NFO")]
LAST_ENTRY = "14:30"
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
    bars = daily_bars(symbol, exchange, 10)
    if len(bars) < 7:
        return None
    stretch = sum(min(b["high"] - b["open"], b["open"] - b["low"]) for b in bars) / len(bars)
    ranges = [b["high"] - b["low"] for b in bars]
    nr = (
        "NR7" if ranges[-1] == min(ranges[-7:]) else "NR4" if ranges[-1] == min(ranges[-4:]) else ""
    )
    open_ = quote(symbol, exchange)["open"]
    return {
        "up": open_ + stretch,
        "down": open_ - stretch,
        "stretch": round(stretch, 2),
        "after": nr,
    }


def trigger(levels: dict, q: dict) -> str | None:
    price = q["last_price"]
    return (
        "long_entry" if price > levels["up"] else "short_entry" if price < levels["down"] else None
    )


def main() -> None:
    if not market_open():
        print("NSE closed; nothing to do today.")
        return
    watch(load_state(), levels_of, trigger, "09:20", LAST_ENTRY)


if __name__ == "__main__":
    main()
