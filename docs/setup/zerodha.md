# Connecting Zerodha (Kite Connect)

OpenTicker talks to Zerodha through your own Kite Connect app. You need a Zerodha account and a Kite Connect subscription that includes market data and historical candles; see Zerodha's current pricing at <https://developers.kite.trade/>.

## 1. Create a Kite Connect app

1. Sign in at <https://developers.kite.trade/> with your Zerodha account.
2. Create a new app.
3. Set **Redirect URL** to `http://127.0.0.1/`. Nothing needs to be listening there: after login the browser tries to load that address and fails, but the address bar still shows the `request_token` OpenTicker needs.
4. Copy the app's **API key** and **API secret**.

## 2. Configure OpenTicker

Copy `.env.example` to `.env` at the repo root and fill in:

```
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret
```

`.env` is gitignored. Never commit it.

## 3. Log in (daily)

Kite sessions expire every day, so this runs once per trading day. Ask your agent to connect Zerodha; it will:

1. call `get_broker_login_url` and show you the link,
2. wait while you log in on Zerodha's own page (OpenTicker never sees your password or TOTP),
3. ask you for the `request_token` from the address bar you land on (`http://127.0.0.1/?request_token=...&action=login&status=success`),
4. call `connect_broker` with it.

The session token is stored encrypted under `~/.openticker` (or `$OPENTICKER_HOME`) and is never returned to the agent. When it expires, tools fail with a message asking to reconnect.

## 4. Load instruments

Ask the agent to run `sync_instruments` once a day. It downloads Zerodha's instrument list (about 80,000 contracts across NSE, BSE, NFO, BFO and MCX) so that symbols like `NIFTY22SEP2623350CE` resolve.
