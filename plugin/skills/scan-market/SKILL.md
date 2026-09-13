---
name: scan-market
description: Use when the user wants the agent to find trade candidates itself rather than naming a symbol - e.g. "scan the market for setups", "find me a trade", "check IT sector stocks for a setup", "scan Nifty 50 for breakouts". Runs the whole news-to-position workflow in one pass.
---

# Scan market

Runs the full autonomous workflow: find candidates from news, verify the
news, check each candidate's chart against whichever technical indicators
actually matter for that setup, and propose a stop/target/size for
whatever survives. Runs entirely in this conversation - it does not
spawn any subagent. All judgment (which candidates are real, which
readings matter, what to size) is yours to make at each stage, not a
script's.

## Steps

### Stage 1: news discovery and verification

1. Work out the scope from what the user said: a specific stock, a
   sector, a named universe (Nifty 50, Nifty 500, midcap, smallcap), or
   nothing (scan broadly).
2. If the user named a universe, resolve it to a symbol list first:
   `uv run python -c "import asyncio, sys; sys.path.insert(0, 'plugin'); from lib.mechanics.nse_index import fetch_index_constituents, INDEX_NIFTY_50; print(asyncio.run(fetch_index_constituents(INDEX_NIFTY_50)))"`
   (swap `INDEX_NIFTY_50` for the constant matching what the user named:
   `INDEX_NIFTY_500`, `INDEX_NIFTY_MIDCAP_150`, `INDEX_NIFTY_SMALLCAP_250`).
   Use this list only to filter which of Stage 1's discovered candidates
   count, not as a scan target to search news for one by one.
3. Call the Exa search tool directly, several times:
   - If scoped to a stock or sector, target the searches at that scope.
   - If unscoped, search broadly: today's market news, notable sector
     moves, earnings, corporate actions, block deals.
   - Prefer exchange filings (NSE/BSE announcements), regulator
     releases, and named mainstream financial outlets over blogs,
     forums, or social posts. A candidate sourced only from a low-quality
     site needs a second, higher-quality source before it counts.
   - Only count a story as "in the news right now" if it is dated within
     the last 48-72 hours. Discard anything older, even if it still
     ranks in search results - the market has likely already priced it.
4. From the results, extract a list of candidate symbols that are
   genuinely active in the news right now, per the recency and source
   bar above. If a universe was named in Step 2, drop any candidate not
   in that list.
5. For each surviving candidate, make one more Exa search call to
   verify the news and judge it against two separate bars:
   - **Materiality**: does it plausibly move earnings, guidance, or
     valuation - an order win, regulatory action, management change,
     M&A, capacity/capex news, a rating or guidance revision - not just
     a routine price mention, an analyst reiterating an old view, or
     the stock's own price move being reported as if it were the news.
   - **Sentiment**: positive, negative, or noise, using the same
     material-vs-routine bar - noise never survives, and negative-and-
     material is dropped in the next step regardless of sentiment.
   Drop any candidate whose news is negative and material, whose news
   doesn't hold up under a closer look, or that fails either bar above.
6. If no candidates survive, tell the user plainly: no eligible news-led
   setups right now. Stop here.

### Stage 2: technical screen

7. For each surviving candidate, decide which technical indicators
   actually matter for that candidate's news story (a breakout story
   wants `breakout`/`support_resistance`; a momentum story wants
   `rsi`/`macd`/`roc`; a volume-driven story wants
   `above_average_volume`/`obv`). Invoke the technical-screen skill for
   that candidate with those indicator names.
8. Read the readings. Decide for yourself whether the chart supports the
   news, weighing whichever indicators you asked for together rather
   than requiring every one of them to agree. Drop any candidate whose
   chart doesn't show a real setup.
9. If no candidates survive, tell the user plainly and stop here.

### Stage 3: positioning

10. If the user hasn't given capital and a risk-per-trade percentage in
    this conversation, ask for both now, before sizing anything real.
11. For each surviving candidate, invoke the position-sizing skill with
    that capital and risk-per-trade percentage.
12. Review the suggested stop, target, and quantity against your own
    read of the setup from Stage 2. Adjust anything that doesn't fit
    the chart's actual structure - these numbers are a starting point.

### Stage 4: report

13. Present the surviving candidates as a shortlist: symbol, why the
    news qualified it, which indicators supported the setup and what
    they showed, and the proposed entry/stop/target/quantity. Say
    plainly this is a suggestion to review, not an executed trade - this
    skill proposes, it does not place orders.
