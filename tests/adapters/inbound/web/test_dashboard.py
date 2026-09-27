"""The Dashboard's routes (ADR 34 in docs/adr)."""

from tests.adapters.inbound.web.conftest import OWN, Web

SAME_ORIGIN = {"origin": OWN}
ORDER = {
    "broker": "fake",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "side": "BUY",
    "quantity": 2,
    "product": "MIS",
}


def test_today_has_the_days_figures_and_no_since_on_the_first_visit(web: Web) -> None:
    client = web.sign_in()
    assert client.post("/api/v1/orders", json=ORDER, headers=SAME_ORIGIN).status_code == 200

    body = client.get("/api/v1/today", params={"broker": "fake"}).json()

    assert body["trading_date"] == "2026-09-22" and body["fills"] == 1
    assert body["net_pnl"] == round(body["before_charges"] - body["charges"], 2)
    assert body["since"] is None and body["points"] == []


def test_setup_says_what_is_left(web: Web) -> None:
    body = web.sign_in().get("/api/v1/setup", params={"broker": "fake"}).json()

    assert body["broker_connected"] is False and body["done"] is False
    assert body["instrument_count"] == 2  # the fixture lists two


def test_history_and_charges_summary(web: Web) -> None:
    client = web.sign_in()
    client.post("/api/v1/orders", json=ORDER, headers=SAME_ORIGIN)
    dates = {"from_date": "2026-09-01", "to_date": "2026-09-30"}

    history = client.get("/api/v1/pnl/history", params={"broker": "fake", **dates}).json()
    charges = client.get("/api/v1/charges/summary", params=dates).json()
    too_long = client.get(
        "/api/v1/pnl/history",
        params={"broker": "fake", "from_date": "2025-01-01", "to_date": "2026-09-30"},
    )

    [today] = history["days"]
    assert today["live"] is True and today["fills"] == 1
    assert charges["months"][0]["month"] == "2026-09" and charges["total"] > 0
    assert too_long.status_code == 422
