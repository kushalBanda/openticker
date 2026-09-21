## What and why

<!-- What changed, and the problem it solves. Link the issue: Fixes #123 -->

## How it was verified

<!-- Tests added or updated. For broker adapters: tested against the real API? -->

## Checklist

- [ ] `uv run pytest`, `uv run mypy src tests` and `uv run ruff check src tests` pass
- [ ] Follows the relevant ADRs in `docs/adr/` (new ADR added if this makes a new design decision)
- [ ] `CHANGELOG.md` updated for user-visible changes
- [ ] No secrets, account data, or market data committed
