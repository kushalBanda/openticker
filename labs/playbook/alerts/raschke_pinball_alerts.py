"""Linda Raschke's Momentum Pinball alerts for raschke-momentum-pinball (stg_3163d4dff087).

From Street Smarts. LBR/RSI = 3-period RSI of the daily net change. Below
30 yesterday: buy a break above today's first-hour high. Above 70: sell a
break below the first-hour low. The book holds overnight; here the
strategy is intraday, so its 1% stop, 0.8% trailing stop and 15:10 exit
close it. Runs 10:15-14:30, after the first hour.
"""

import json
import os
import time
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

SYMBOLS = [(s, "NSE") for s in ["TATASTEEL", "ADANIENT", "NTPC", "POWERGRID"]]
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


def rsi(values: list[float], period: int) -> float:
    gains = losses = 0.0
    for change in values[-period:]:
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)


def first_hour(symbol: str, exchange: str) -> tuple[float, float] | None:
    today = now().date().isoformat()
    bars = (
        API.get(
            "/bars",
            params={
                "broker": "zerodha",
                "symbol": symbol,
                "exchange": exchange,
                "interval": "15minute",
                "start_date": today,
                "end_date": today,
            },
        )
        .raise_for_status()
        .json()["bars"]
    )
    hour = [b for b in bars if "09:15" <= b["timestamp"][11:16] < "10:15"]
    return (max(b["high"] for b in hour), min(b["low"] for b in hour)) if len(hour) == 4 else None


def levels_of(symbol: str, exchange: str) -> dict | None:
    closes = [b["close"] for b in daily_bars(symbol, exchange, 6)]
    if len(closes) < 6:
        return None
    changes = [b - a for a, b in pairwise(closes)]
    lbr = rsi(changes, 3)
    if 30 <= lbr <= 70:
        return None
    hour = first_hour(symbol, exchange)
    if hour is None:
        return None
    side = "long" if lbr < 30 else "short"
    return {"side": side, "level": hour[0] if side == "long" else hour[1], "lbr_rsi": round(lbr, 1)}


def trigger(levels: dict, q: dict) -> str | None:
    price = q["last_price"]
    if levels["side"] == "long":
        return "long_entry" if price > levels["level"] else None
    return "short_entry" if price < levels["level"] else None


def main() -> None:
    if not market_open():
        print("NSE closed; nothing to do today.")
        return
    watch(load_state(), levels_of, trigger, "10:15", LAST_ENTRY)


if __name__ == "__main__":
    main()
