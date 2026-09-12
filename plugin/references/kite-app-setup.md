# Registering a Kite Connect app

This plugin does not provide Kite credentials for you. Kite Connect API access is a paid Zerodha subscription (~₹500/month) — this is an external prerequisite, unrelated to this plugin, and cannot be automated away.

1. Go to `https://developers.kite.trade/` and sign in with your Zerodha account.
2. Create a new Kite Connect app.
3. Set the app's **Redirect URL** to exactly:
   ```
   http://127.0.0.1:8765/kite/callback
   ```
   This must match `plugin/skills/connect-adapter/scripts/connect_adapter.py`'s `CALLBACK_PORT`/`CALLBACK_PATH`. If you ever change those, update the Redirect URL in the Kite developer console to match.
4. Note the app's **API Key** and **API Secret**.
5. Create a `.env` file at the repo root (already gitignored — never commit it) with:
   ```
   KITE_API_KEY=your_api_key
   KITE_API_SECRET=your_api_secret
   ```
6. Run the connect-adapter skill. It opens Kite's login page in your browser, waits for the redirect, and stores the resulting session locally — your API Secret never leaves this exchange, and your Kite password never touches this plugin at all (you type it only on Zerodha's own login page).
