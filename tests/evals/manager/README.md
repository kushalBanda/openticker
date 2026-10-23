# Desk manager evals

Three desks the manager got wrong on a real day (ADR 44), each given to a real harness for one turn, then graded on the desk that turn leaves. They spend real money, so pytest never collects them (`collect_ignore` in `tests/conftest.py`): run them by hand when the manager's prompt, its skill or what a wake tells it changes.

```
uv run python -m tests.evals.manager.run --model haiku           # all three, Claude Code
uv run python -m tests.evals.manager.run --model sonnet --effort high
uv run python -m tests.evals.manager.run --harness codex         # Codex's default model
uv run python -m tests.evals.manager.run --scenario own_stop_acted --repeat 3
uv run python -m tests.evals.manager.run --show-wake             # seed and print each wake; free
```

Each scenario gets a fresh `OPENTICKER_HOME` in the system's temp folder. The desk is a NIFTY market from the test fixtures, priced by a fake broker registered as `zerodha`. It is served over MCP as `openticker-serve` serves it, at a free local port, on a clock that starts at the scenario's moment of 22 Sep 2026 and then runs at real speed. The turn runs in `labs/` with its real `AGENTS.md` and `manage-desk` skill, through the daemon's own chat lane. Nothing touches `~/.openticker`, the real broker, Slack or email.

| Scenario | The wake | Passes when |
|---|---|---|
| `blind_plan_then_prices_back` | restored, at 09:11: the 09:04 plan gave three straddles capital 0 while the session was down, and left them scheduled for 09:45 | nothing is undone (each runs with a stop or is held out at capital 0, and the plan is new), it called `set_manager_plan`, and it asks the user nothing |
| `unguarded_at_a_check_in` | the hourly look at 11:50: three straddles have run since 09:30 with capital and no stop line | nothing is undone, each still running has a stop within 0.5 to 2 times its suggested −3,000, and it asks nothing |
| `own_stop_acted` | broke, at 10:31: a straddle's own combined stop closed it at −3,263, inside its −5,000 line | it isn't restarted, a minute later the server would not wake it again for a line, undone or breakage, the answer says a stop closed it, and it asks nothing |

"Asks nothing" means the answer has no question mark and none of "want me to", "should I", "say the word", "let me know" and the like.

## Reading a result

Each scenario prints PASS or FAIL with its time and cost, each failed check, the tools it called in order and its answer. The last line counts the passes and the total cost; the exit code is 0 only when all passed. The scenario's home is left in the temp folder (its path starts `openticker-eval-<scenario>-`), with the turn's events in `agent_jobs/`.

The eval runs no P&L recorder, so `desk_today` is empty and a model may say so; each strategy's today is there. A run of all three cost about $0.04 on Haiku, $0.40 on Sonnet and $0.90 on Opus in October 2026; `--budget` caps each turn (Claude Code only, $2 by default). Results by model are recorded in ADR 44.
