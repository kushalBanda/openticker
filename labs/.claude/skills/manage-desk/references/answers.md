# Worked answers

Four answers in the shape the user reads best. The figures are an example day's; yours come from the tools. Plain sentences, the figure behind each decision, nothing the user already sees on the page repeated at length.

## The plan, after a bad night

The wake carried: the broker session expired at 21:40; 6 scripts ended (failed); 18 orders refused for insufficient funds; 5 strategies stopped for lost prices, −₹14,226 together. Yesterday's close said "run the weekly straddle small".

> Yesterday's loss was the session, not the strategies: the broker session expired at 21:40, prices stopped, and five positional runs closed for lost prices at 09:15 (−₹14,226 together, straddle −₹5,558 the largest). The 6 alert scripts crashed on the same expiry and the 18 refused orders were their retries. The session is back this morning (quotes flow).
>
> Today: the weekly straddle runs with ₹2,00,000 and a −₹6,000 stop (its median losing run is −₹2,880; this lets one bad run cost two). The 4 positional strategies stay stopped until their alert scripts run again: their entries depend on them. Scripts restarted: orb-alerts, momentum-alerts. Desk stop −₹20,000.
>
> Relied on: "Restart nothing that needs prices until quotes flow". Next look 09:45, when the straddle enters.

## Something broke

The wake carried: "Strategy 'nifty-strangle-weekly' stopped: tick_stale, realized −₹5,557.50".

> The strangle closed for lost prices at 13:33 (−₹5,558, −₹32 charges): quotes for its PE leg stopped for 60s. Quotes are flowing again, but its entry window has passed, so it stays stopped today. Desk now −₹6,120 against a −₹20,000 stop. No change to the other lines.

## A check-in with nothing to do

> Nothing changed since 11:40: the straddle is open at −₹420 against its −₹6,000 stop, nothing else runs. No next look: a breakage or the line would wake me.

## The close

> Desk +₹3,174: +₹1,050 closed, +₹2,244 still open (the NIFTY futures trend), −₹120 charges. The straddle made +₹1,050 and paid ₹87; the futures trend is up on paper and held overnight by design.
>
> What worked: waiting for quotes before restarting anything. What didn't: the protective put sat at capital 0 all day; its review is due (started). Tomorrow: the same lines, with the futures trend's stop moved to −₹8,000 as it carries a day's gain.

## What to leave out

- A list of every tool you called.
- Numbers without a source ("about −₹5k").
- A next look "to check in": the hourly look already does that.
- Promises about what the market will do.
