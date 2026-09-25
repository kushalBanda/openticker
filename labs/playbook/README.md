# Playbook

How to use `labs/` with your coding agent.

## Setup

1. Follow the main README to install OpenTicker (`uv sync`) and set your broker's API key in `.env` at the repository root.
2. Start the server that watches strategies, in its own terminal, and leave it running:

   ```bash
   uv run openticker-serve
   ```

3. Open this folder in your agent:

   ```bash
   cd labs
   claude        # Claude Code: approve the openticker MCP server when asked
   codex         # Codex: trust the folder when asked, so it loads .codex/config.toml
   ```

4. Ask the agent to connect your broker; it walks you through the login.

## Your first strategy

Describe an idea in plain words, for example:

> Sell a weekly NIFTY iron condor at 9:20, wings two strikes apart, exit at 15:00, and stop the day if it loses ₹3,000.

The `new-strategy` skill asks what it needs, shows you the real contracts and prices, saves the strategy and writes a note about it in `notes/`. It doesn't start anything. Say "start it" or "schedule it" when you're ready.

## What's where

| Path | What |
|---|---|
| `AGENTS.md`, `CLAUDE.md` | Instructions both agents read |
| `.mcp.json`, `.codex/config.toml` | How each agent reaches OpenTicker |
| `.claude/skills/`, `.agents/skills/` | The same skills, for Claude Code and Codex |
| `notes/` | Your research log, one note per strategy (not committed) |
| `research/` | Scratch work (not committed) |

Everything runs on paper: orders go to a local sandbox with virtual capital, never to your broker.
