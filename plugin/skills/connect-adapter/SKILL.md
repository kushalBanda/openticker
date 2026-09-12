---
name: connect-adapter
description: Use when the user wants to connect a broker/market-data adapter (Kite) to this plugin, or asks to log in, connect, or authenticate a provider before running research.
---

# Connect adapter

Connects this plugin to a market-data/broker provider by running `plugin/skills/connect-adapter/scripts/connect_adapter.py`, storing the result locally in `~/.quant-plugin/credentials.duckdb`. No server is involved - the script talks to the provider directly.

**Providers currently supported: Kite only.** Groww is planned but not yet built (see `docs/v2/quant-plugin/issues/04-connect-adapter-groww-login.md`, deferred). If the user asks for Groww, tell them plainly it isn't available yet rather than attempting it.

## Steps

1. Check whether `KITE_API_KEY` and `KITE_API_SECRET` are available (a `.env` at the repo root, or already exported). If not, point the user at `plugin/references/kite-app-setup.md` and stop - do not run the script without these.
2. Run `uv run python plugin/skills/connect-adapter/scripts/connect_adapter.py --provider kite`. This opens Kite's login page in the user's browser, waits for the redirect on `http://127.0.0.1:8765/kite/callback`, exchanges the resulting token, and stores the session. The script prints one JSON object to stdout.
3. Tell the user what happened in plain language:
   - Success: stdout is `{"provider": "kite", "status": "connected"}` - confirm "connected as Kite".
   - Missing app credentials: point them at `plugin/references/kite-app-setup.md`.
   - Login exchange failed: stdout has an `"error"` key - tell the user plainly and offer to retry. The script does not leave a half-written entry in the store on failure.
4. Do not print or repeat the user's `api_key`/`access_token` back into the conversation once stored - the point of this flow is that raw credentials stay local.
