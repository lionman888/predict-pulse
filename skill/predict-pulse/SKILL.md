---
name: predict-pulse
description: Deploy, configure, inspect, or troubleshoot the read-only Predict Pulse market-anomaly monitor, including probability, volume, liquidity, spread, Bark, Telegram, VPS, and Codex workflows. Do not use for placing trades or managing wallets.
---

# Predict Pulse

Built by [Lionman Labs](https://www.lionmanlabs.top) · [@lionman888888](https://x.com/lionman888888)

Use the repository's deterministic installer and commands instead of rewriting the monitor.

## Workflow

1. Ask for the trading style first: fast/sensitive, balanced, or low-noise. Use balanced when the user does not choose.
2. Confirm local-machine or VPS deployment. Prefer VPS for continuous monitoring.
3. Obtain the Predict API key and notification channel: Bark, Telegram, both, or console only.
4. Clone this repository and run `deploy/install.sh` with secrets passed as environment variables. Never add secrets to Git or generated public files.
5. Apply the chosen thresholds to `/etc/predict-pulse/config.json`, validate the estimated API usage, and restart both services.
6. Run one read-only cycle, test the notification channel, and check `/api/health`.
7. Report the monitored-market count, snapshot freshness, notification result, dashboard URL, and active thresholds in plain language.

## Trading presets

- Fast/sensitive: 15m probability 3 points, 1h probability 6 points, volume +$500, liquidity ±20%, spread ±3 points, 15-minute cooldown.
- Balanced: 15m probability 5 points, 1h probability 10 points, volume +$1,000, liquidity ±25%, spread ±5 points, 30-minute cooldown.
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
