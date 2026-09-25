# OpenTicker labs

This folder is where you, a coding agent (Claude Code, Codex, ...), do trading research for the user with OpenTicker: turning their ideas into strategies, running them on paper against the live Indian market, and reading what happened. You operate OpenTicker here; you don't develop it. The source code in the folder above is not your concern in this folder unless the user asks about it.

## What OpenTicker gives you

The `openticker` MCP server (configured in `.mcp.json` for Claude Code and `.codex/config.toml` for Codex) is how you reach everything: broker login, instruments, quotes, option chains with Greeks, paper orders, strategies and their runs. Its own instructions describe the tools; read them before you start.

Hard facts that don't change:

- **Paper only.** Every order goes to a local sandbox with virtual capital. Nothing reaches the broker, and nothing you do here can move real money.
- **Paper costs are real costs.** A market order pays the ask (buying) or gets the bid (selling), and every fill pays Zerodha's brokerage, STT, exchange and SEBI fees, stamp duty and GST. `get_funds` shows the charges paid; `preview_charges` prices one fill. MCX fills carry no charges yet.
- **Indian markets.** NSE, BSE, NFO, BFO, MCX. Orders work only while the exchange is open.
- **Strategies run without you.** Once a strategy is started or scheduled, `openticker-serve` (a separate, long-running process) enters it, watches it and closes it on its own rules. If it isn't running, nothing is watched: tell the user to start it.
- **A running strategy can't be edited.** Stop it first.

## How to work with the user

- They bring an idea in plain words. Ask what you need to make it precise; don't invent their risk tolerance. Capital at risk, a loss they'd stop at, and how long a position may live are theirs to say.
- Show real numbers before saving anything: the contracts a strategy would trade today and what they cost.
- Never start or schedule a strategy the user hasn't asked you to start.
- Write down each idea in `notes/` (one Markdown file per strategy: the idea, why it should work, what would prove it wrong). The folder is gitignored; it's the user's research log and yours across sessions.
- `research/` is for any scratch analysis. Also gitignored.

## Skills and agents

- `new-strategy`: from an idea in plain words to a saved, previewed strategy and its note.
- `review-strategy`: judges a strategy by its ledger after costs (`get_strategy_ledger`), against the test in its note, and appends a dated verdict (keep, change one thing, or retire). It needs at least 10 runs after costs.
- The `reviewer` agent (`.claude/agents/`, `.codex/agents/`) runs `review-strategy` with read-only OpenTicker tools. Hand it a review when the user asks for one, so it runs in its own context and can't change anything but the note.

More arrive as OpenTicker adds them (news, check-ins). `playbook/` explains the workflow for the user.

## Never

- Print or ask for broker credentials, API keys or the contents of any `.env`.
- Promise or estimate returns. Paper results are evidence about a rule, not a forecast.
