# Reading the desk

## Contents
- Today's money; explaining the desk's figure
- How a run ended
- Your lines: capital, stops, sizing a stop
- Who owns what
- Costs of looking

What the numbers you read mean, how your lines act, and who owns what. Read it before a session's first plan and whenever a figure puzzles you.

## Today's money

Every "today" figure keeps the market apart from the charges.

`get_manager` gives `desk_today`, the paper account at the latest recorded minute:

- `gross`: what trades closed today made at their fill prices, before charges.
- `open`: how much what's still open moved since the last close. A position held overnight counts only today's move.
- `charges`: what today's fills paid: brokerage, STT, exchange and SEBI fees, stamp duty, GST. Always a cost.
- `net`: gross + open − charges. The desk line's stop is checked against it.

`list_strategies` gives each strategy's own:

- `today_gross` and `today_charges`: the fills it made today, **whatever day their run started**. A positional run entered yesterday and closed this morning counts today, with today's exit charges only.
- `today_pnl`: their difference. Open legs are not in it: a strategy still holding shows only what it closed and paid.
- `daily_used_before`: realized P&L of its other runs started today, the part its own daily loss limit has already used.

Each line in `get_manager` carries the same split as `today` (no `open` for a strategy line).

### Explaining the desk's figure

Account for the desk's net before anything else:

1. Add the strategies' `today_gross`. The rest of `desk_today.gross` came from hand-placed trades, scripts and your own: `get_tradebook` lists today's fills with who placed each (`triggered_by`).
2. `desk_today.open` is what open positions moved: `get_positions` shows which.
3. `desk_today.charges` is every fill's charges. Many small fills (a strategy that re-enters, an alert script) can cost more than they make.

Say it in one or two sentences: "Desk −₹15,846: −₹7,016 closed (straddle −₹5,558, protective put −₹4,632, covered call +₹3,525), −₹7,243 still open (the RELIANCE holding), −₹1,587 charges." If the parts don't come to the whole, say by how much and what you couldn't place.

## How a run ended

`last_run_end` on each strategy: `reason`, `detail` (in words, with who asked for a stop), `at`.

| reason | means | before you restart it |
|---|---|---|
| `tick_stale` | its prices were lost (no tick or quote for a minute) and it closed | prices must flow again: `get_market_status`, `get_quote` on its contracts |
| `combined_stop_loss`, `daily_loss_limit`, `profit_lock` | its own limits closed it, as designed | a fresh reason to expect a different day |
| `kill` | someone pulled the kill switch | it stays locked until `release_kill_switch`; one you threw on an earlier day is listed as `locked` |
| `manual` | someone stopped it; `detail` says who (`stop by ui` is the user) | the user's stop stands for the day |
| `schedule`, `expiry`, `legs_closed`, `combined_target` | it finished on its rules | nothing |
| `error`, `recovery_failed` | something failed inside the server | read `get_strategy_run`; tell the user |

## Your lines

A line is capital and a stop for one strategy, one script, your own trades (`own`) or the whole desk (`desk`).

- **Capital is your stated allocation.** A strategy trades its own definition's size whatever its capital. Capital 0 is the one figure the server acts on: it holds the strategy or script out (no scheduled entry, no alert's entry, no scheduled start) for the trading day you set it for (the user's capital 0 until they change it), or until you're turned off. It closes nothing, so a run already open needs `stop_strategy`; until then `undone` lists it as `contradicted`.
- **A stop acts only when you look.** When a line's `today.net` is at or past its stop, a `line` wake comes; you decide whether to stop the strategy. Each strategy's own stop loss and daily loss limit act at once, without you. So a stop line protects against a day the strategy's own rules allow but you wouldn't.
- **Sizing a stop.** `suggested_stop` (in `get_strategy_ledger` and in each `undone` item) does the arithmetic:
  - with 10 or more runs after costs, 1.75 times its median losing run, never tighter than its own combined stop (it would cross before the strategy's own rules act);
  - with fewer, its own combined stop, else its daily loss limit;
  - with neither, none.

  Its `basis` says which; give it as the line's reason. Go wider only with a reason of your own. With no suggestion, size it from the strategy's own leg stops and lot size, and say the record is thin.
- **Set it before it trades.** A stop set at or past today's figure is already crossed, so it wakes no one and protects nothing for today.
- **The desk stop** is the day's loss you'd accept across everything: usually well under the sum of the strategies' stops, since they rarely lose together.

## Who owns what

- **The user's lines** (`set_by: you`) stand until they hand them back. `kept_yours` tells you when yours lost.
- **Schedules** are the user's, and stay as they set them. You decide what runs today with your lines (capital 0 holds one out), `start_strategy`, `start_script` and `stop_strategy`, each with a reason in your answer. You don't need to ask: the user handed you the desk.
- **Alert scripts.** A signal strategy trades only on alerts. When a hosted script sends them, the strategy is as alive as that script: `list_scripts` says whether it runs or is scheduled, and `undone` lists the strategy as `starved` when it won't run today.
- **A strategy stays the user's** when its line is theirs, or they stopped it by hand today (`last_run_end.detail` is `stop by ui`), or its kill switch is on.
- **Signing in to the broker** is the user's alone. An expired session stops prices and with them every running strategy; tell the user to sign in again from Settings.

## Costs of looking

Your looks cost money too. Decisive looks (the plan, the close, a breakage, a crossed line, the user's Look now) may run on a stronger model; check-ins (the time you set, the hourly look) on a lighter one. A check-in with nothing to do should end in a line.
