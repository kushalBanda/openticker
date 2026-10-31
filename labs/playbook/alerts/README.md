# Alert scripts

Hosted scripts that watch prices and post alerts to a signal strategy's URL (ADR 24 and ADR 25 in `docs/adr/`). Each one names the strategy it feeds and its rules in its docstring.

| Script | Rule | Source |
| --- | --- | --- |
| `crabel_orb_alerts.py` | Opening range breakout: open ± the 10-day average stretch, NR4/NR7 logged | Toby Crabel, *Day Trading with Short Term Price Patterns and Opening Range Breakout* (1990) |
| `williams_vbo_alerts.py` | Volatility breakout: open ± 0.5 × yesterday's range | Larry Williams |
| `raschke_8020_alerts.py` | 80-20 reversal: yesterday opened at one end of its range and closed at the other; today pierces and reclaims it | Connors and Raschke, *Street Smarts* (1995) |
| `raschke_pinball_alerts.py` | Momentum Pinball: 3-period RSI of the daily change, then a first-hour breakout | Connors and Raschke, *Street Smarts* (1995) |

## Using one

1. Create the signal strategy with legs for the script's `SYMBOLS`, and its alert URL (`create_strategy_webhook`).
2. Upload the script (`create_script`) and schedule it for the hours in its docstring.
3. Put the token, the last part of the alert URL (`otw_...`), in a file named `alert_token` in the script's folder, `$OPENTICKER_HOME/scripts/<script id>/`. The token is the alert URL's only credential: keep it out of the source and out of git.
