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
.brand::before { content: ""; width: 10px; height: 10px; border-radius: 3px; background: #f5c518; }
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
