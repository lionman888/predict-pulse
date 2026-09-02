---
name: predict-pulse
description: Deploy, configure, inspect, or troubleshoot the read-only Predict Pulse market-anomaly monitor, including probability, volume, liquidity, spread, Bark, Telegram, VPS, and Codex workflows. Do not use for placing trades or managing wallets.
---

# Predict Pulse

Use the repository's deterministic installer and commands instead of rewriting the monitor.

## Workflow

1. Confirm whether the user wants local-machine or VPS deployment. Prefer VPS for continuous monitoring.
2. Obtain the user's Predict API key and chosen notification channel: Bark, Telegram, both, or console only.
3. Clone this repository and run `deploy/install.sh` with secrets passed as environment variables. Never add secrets to Git or generated public files.
4. Verify both `predict-pulse` and `predict-pulse-web` services, then run one read-only cycle and check `/api/health`.
5. Report the monitored-market count, snapshot freshness, notification result, and dashboard URL.

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
