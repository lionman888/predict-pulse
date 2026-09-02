---
name: predict-pulse
description: Deploy, configure, inspect, or troubleshoot the read-only Predict Pulse market-anomaly monitor, including probability, volume, liquidity, spread, Bark, Telegram, VPS, and Codex workflows. Do not use for placing trades or managing wallets.
---

# Predict Pulse

Built by [Lionman Labs](https://www.lionmanlabs.top) · [@lionman888888](https://x.com/lionman888888)

Use the repository's deterministic installer and commands instead of rewriting the monitor.

## Workflow

1. Ask what to monitor: all markets, one or more categories, or a personal watchlist made from Predict market links. Use all markets when the user does not choose.
2. Ask for the trading style: fast/sensitive, balanced, or low-noise. Use balanced when the user does not choose.
3. Confirm local-machine or VPS deployment. Prefer VPS for continuous monitoring.
4. Obtain the Predict API key and notification channel: Bark, Telegram, both, or console only.
5. Clone this repository and run `deploy/install.sh` with secrets passed as environment variables. Never add secrets to Git or generated public files.
6. Apply the chosen monitoring mode and thresholds to `/etc/predict-pulse/config.json`, validate the estimated API usage, and restart both services.
7. Run one read-only cycle, test the notification channel, and check `/api/health`.
8. Report the monitoring scope, monitored-market count, snapshot freshness, notification result, dashboard URL, and active thresholds in plain language.

## Monitoring modes

- `all`: monitor the configured number of open markets.
- `category`: set `monitoring.segments` to any combination of `crypto`, `esports`, `sports`, `politics`, and `other`.
- `watchlist`: paste one or more `https://predict.fun/category/...` links into `monitoring.market_urls`; all open contracts under those links are monitored.

The public dashboard lets visitors filter the collected universe by category and save a personal link watchlist in browser storage. A private deployment applies the chosen mode before alerting, so unrelated markets never reach Bark or Telegram.

## Trading presets

- Fast/sensitive: 15m probability 3 points, 1h probability 6 points, volume +$500, liquidity ±20%, spread ±3 points, 15-minute cooldown.
- Balanced (default): 15m probability 3 points, 1h probability 6 points, volume +$1,000, liquidity ±30%, spread ±3 points, 20-minute cooldown.
- Low-noise: 15m probability 8 points, 1h probability 15 points, volume +$2,500, liquidity ±40%, spread ±8 points, 60-minute cooldown.

Treat the displayed probability as the orderbook midpoint, not an executable quote. The dashboard's ask is the approximate buy price and its bid is the approximate sell price. Never describe midpoint movement alone as guaranteed profit or a trade recommendation.

## Commands

```bash
PYTHONPATH=/opt/predict-pulse python3 -m predict_pulse.pulse \
  --config /etc/predict-pulse/config.json --once --dry-run

PYTHONPATH=/opt/predict-pulse python3 -m predict_pulse.pulse \
  --config /etc/predict-pulse/config.json --status

PYTHONPATH=/opt/predict-pulse python3 -m predict_pulse.pulse \
  --config /etc/predict-pulse/config.json --test-notify
```

The application is read-only. Do not request wallet keys, submit orders, or add trading behavior when using this skill.
