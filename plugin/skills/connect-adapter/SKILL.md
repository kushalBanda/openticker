---
name: connect-adapter
description: Use when the user wants to connect a broker/market-data adapter (Kite) to this plugin, or asks to log in, connect, or authenticate a provider before running research.
allowed-tools: Bash
---

# Connect adapter

Connects this plugin to a market-data/broker provider, storing the result locally in `~/.quant-plugin/credentials.duckdb` (see `plugin/scripts/state.py`). No server is involved - the script talks to the provider directly.

**Providers currently supported: Kite only.** Groww is planned but not yet built (see `docs/v2/quant-plugin/issues/04-connect-adapter-groww-login.md`, deferred). If the user asks for Groww, tell them plainly it isn't available yet rather than attempting it.

## Steps

1. Check whether `KITE_API_KEY` and `KITE_API_SECRET` are available (a `.env` at the repo root, or already exported). If not, point the user at `plugin/references/kite-app-setup.md` and stop - do not attempt the login flow without these.
2. Run:
   ```
   uv run python plugin/scripts/auth_kite.py
   ```
   from the repo root. This opens Kite's login page in the user's browser, waits for the redirect on `http://127.0.0.1:8765/kite/callback`, exchanges the resulting token, and stores the session.
3. Tell the user what happened in plain language:
   - Success: confirm "connected as Kite" (the script prints this on success).
   - Missing app credentials: point them at `plugin/references/kite-app-setup.md`.
   - Login exchange failed: tell them plainly and offer to retry - the script does not leave a half-written entry in the store on failure.
4. Do not print or repeat the user's `api_key`/`access_token` back into the conversation once stored - the point of this flow is that raw credentials stay local.
