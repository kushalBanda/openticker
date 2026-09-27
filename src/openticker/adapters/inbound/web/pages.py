"""The two pages the server writes itself: a sign-in link that can't be used,
and the web app not built yet (ADR 30 and ADR 31 in docs/adr). Plain HTML in
the app's colours, light or dark as the system is."""

from html import escape

_STYLE = """
:root { color-scheme: light dark; --ground: #f5f5f7; --tile: #fff; --ink: #1d1d1f;
  --muted: #6e6e73; --code: #e8e8ed; }
@media (prefers-color-scheme: dark) { :root { --ground: #000; --tile: #161617;
  --ink: #f5f5f7; --muted: #86868b; --code: #2a2a2d; } }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--ground);
  color: var(--ink); font: 15px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", Inter,
  "Segoe UI", sans-serif; letter-spacing: -0.01em; }
main { width: 440px; margin: 24px; padding: 24px; border-radius: 18px; background: var(--tile); }
.brand { display: flex; align-items: center; gap: 8px; margin-bottom: 20px; font-weight: 700;
  font-size: 20px; line-height: 24px; letter-spacing: -0.01em; }
.brand::before { content: ""; width: 5px; height: 22px; background: no-repeat center / contain
  url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 42 200'%3E%3Crect\
 x='19' width='4' height='200' rx='2' fill='%23ffcc00'/%3E%3Crect x='1' y='20' width='40' height='160'\
 rx='3' fill='%23ffcc00'/%3E%3C/svg%3E"); }
h1 { margin: 0 0 10px; font-size: 28px; line-height: 34px; letter-spacing: -0.025em; font-weight: 600; }
p { margin: 0 0 16px; color: var(--muted); }
p.note { margin: 16px 0 0; font-size: 12.5px; line-height: 18px; }
code { display: block; padding: 12px 16px; border-radius: 12px; background: var(--code);
  color: var(--ink); font: 14px/1.4 ui-monospace, "SF Mono", Menlo, monospace; }
"""


def _page(title: str, heading: str, body: str) -> str:
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)} · OpenTicker</title><style>{_STYLE}</style></head>"
        f'<body><main><div class="brand">OpenTicker</div><h1>{escape(heading)}</h1>{body}'
        "</main></body></html>"
    )


def link_expired() -> str:
    return _page(
        "Sign in",
        "This sign-in link has expired",
        "<p>Links work once and for 10 minutes. Get a fresh one from the terminal running "
        "OpenTicker:</p><code>openticker-serve ui login</code>"
        '<p class="note">OpenTicker only listens on this computer. Nobody else on your network '
        "can open it.</p>",
    )


def not_built() -> str:
    return _page(
        "Not built",
        "The web app isn't built",
        "<p>You're running from a source checkout. Build it once, then reload:</p>"
        "<code>cd ui &amp;&amp; pnpm install &amp;&amp; pnpm build</code>"
        '<p class="note">The REST API at /api/v1 and MCP at /mcp work without it.</p>',
    )


def sign_in_first() -> str:
    return _page(
        "Sign in",
        "Sign in to OpenTicker first",
        "<p>The broker sent you back here, but this browser isn't signed in to OpenTicker, "
        "so the login wasn't kept. Get a sign-in link from the terminal running OpenTicker, "
        "then connect the broker again from Settings:</p><code>openticker-serve ui login</code>",
    )


def bounce(url: str) -> str:
    """Opens `url` (this server's own) from this server's page."""
    target = escape(url, quote=True)
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0;url={target}">'
        f"<title>Connecting · OpenTicker</title><style>{_STYLE}</style></head>"
        f'<body><main><div class="brand">OpenTicker</div><p>Connecting…</p>'
        f'<p><a href="{target}">Continue</a></p></main></body></html>'
    )
