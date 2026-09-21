# Contributing to OpenTicker

Thanks for your interest! OpenTicker is early, so there's plenty of room to shape it.

## Ways to help

- **Add a broker.** Implement `BrokerPort` (`src/openticker/ports/broker_port.py`) for your broker and register it in `adapters/brokers/registry.py`. `adapters/brokers/zerodha/` is the reference implementation. Open a "New broker" issue first so work isn't duplicated.
- **Pick up an issue** labeled `good first issue` or `help wanted`.
- **Report bugs** and **propose features** through the issue templates.
- **Improve docs**, especially setup guides and examples of agent workflows.

For anything larger than a small fix, open an issue to discuss the approach before writing code.

## Development setup

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run mypy src tests
uv run ruff check src tests
```

All three must pass; CI runs the same checks on every pull request. Tests never touch the network or your real data: `tests/conftest.py` isolates `OPENTICKER_HOME` per test, and `tests/fixtures/fake_broker.py` stands in for a real broker.

Optional but recommended: install the pre-commit hooks (ruff, mypy, and a secret scanner).

```bash
uv tool install pre-commit
pre-commit install
```

## Ground rules

- **Read the relevant ADR first.** Design decisions are recorded in [docs/adr/](docs/adr/). If your change reverses or extends one, say so in the PR, and add a new ADR for any new decision a future contributor would need to understand.
- **Respect the architecture** (ADR 1): `core/` has no I/O; `core/` and `ports/` never import from `adapters/` or `use_cases/`; inbound adapters never special-case a broker by name.
- **MCP tools follow ADR 8**: title, annotations, a description on every parameter, a Pydantic result model, bounded responses. A test enforces this.
- **Type everything.** `mypy --strict` must pass.
- **Test behavior, not implementation.** Every bug fix comes with a test that fails without it.
- **Never commit secrets**, real account data, or downloaded market data.
- **Write only original code.** Don't copy code from other projects unless its license is compatible with MIT and you credit it. In particular, no code from AGPL or GPL projects.
- **Order placement stays sandbox-only** (ADR 6). Live trading will need its own design and review.

## Pull requests

- Keep each PR focused on one change.
- Describe what changed and why, and how you verified it. For broker adapters, say whether you tested against the real API.
- Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- Add a line to the `Unreleased` section of [CHANGELOG.md](CHANGELOG.md) for user-visible changes.

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE), and to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
