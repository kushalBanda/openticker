# Troubleshooting

## The broker session expired

`<since_last_close>` or `<broke>` says "The session expired". Prices stop with it, so every running strategy stops for lost prices within a minute, and scripts that read prices crash.

- You can't sign in: it's the user's. Say plainly, first in your answer, that they need to sign in again from Settings.
- `get_market_status` and a `get_quote` on one contract tell you whether prices flow again.
- Restart nothing that needs prices until they do, and unschedule what would enter before then: a strategy entering blind closes for lost prices.
- When they sign in, a "prices back" wake comes (`undone` lists `blind_plan`): plan again from the desk as it is then.

## A strategy stopped for lost prices (`tick_stale`)

Its prices went quiet for a minute and it closed its legs. Read `get_strategy_run` for which leg. Restart it (`start_strategy`) only if prices flow again and its entry rules still make sense today; a positional run closed this way has already paid its exit charges.

## A script crashed

`get_script_logs` shows why. A script that crashed on the same session expiry will crash again until prices return. Restart with `start_script` once they do; a script that crashes on its own code is the user's to fix: name the error line.

## Orders refused

"Insufficient sandbox funds" means the paper account's free margin ran out: `get_funds`. Many refusals in a row are usually one script retrying; count them as one cause.

## `set_manager_numbers` returned `kept_yours`

The user's numbers stood over yours. Say once what you wanted and why; don't ask again on later looks unless the evidence changes.

## A tool refused

The error says how to recover (a wrong id, a strategy already running, a market closed). Fix and retry once. If it refuses again, say what you tried and what it said, and move on.

## The figures don't add up

The desk's figure is the paper account's; the strategies' are their own fills. A gap is usually hand-placed trades, your own, or scripts: `get_tradebook` names who placed each fill. If a gap is still there, say how much and that you couldn't place it. Don't spread it across strategies.

## You can't explain something

Say so, say what you looked at, and what would tell you. A short "I can't tell why X; Y would show it" is worth more than a guess.
