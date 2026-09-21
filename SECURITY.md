# Security Policy

OpenTicker holds broker credentials and can act on a brokerage account, so security reports get priority.

## Reporting a vulnerability

Please **do not open a public issue.** Report privately through GitHub: the repository's **Security** tab, then **Report a vulnerability**. Include what you found, how to reproduce it, and the impact you expect.

You should get an acknowledgement within a few days. Once a fix is ready, it's released and the advisory is published with credit to you, unless you prefer otherwise.

## Supported versions

OpenTicker is pre-1.0. Only the latest commit on `main` receives security fixes.

## How OpenTicker handles secrets

- **Broker API key and secret** are read from `.env` (gitignored) or the environment. They are never written to OpenTicker's databases.
- **Broker session tokens** are encrypted at rest with Fernet (AES-128-CBC with HMAC-SHA256). The key is generated locally at `<OPENTICKER_HOME>/secret.key` with owner-only permissions (`0600`). Anyone who can read that file and the database can decrypt the token, so protect your home directory accordingly.
- **No tool returns a session token or API secret.** Error messages passed to agents contain status codes and broker error text, never credentials.
- **Your broker password and 2FA** are entered only on the broker's own login page. OpenTicker never sees them.
- **Nothing leaves your machine** except calls to your broker's API.

## Scope

In scope: anything that could leak credentials, act on an account without the user's intent, bypass the sandbox restriction on order placement, or let tool input from an agent reach unintended files, queries or network destinations.

Out of scope: compromise of the machine OpenTicker runs on, and the behavior of the MCP client or model driving it.
