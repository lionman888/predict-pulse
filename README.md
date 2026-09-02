# Predict Pulse

Open-source, read-only market intelligence for [Predict](https://predict.fun).

Predict Pulse watches probability, 24-hour volume, liquidity, and spread changes; stores historical snapshots in SQLite; and sends deduplicated alerts through Bark or Telegram. It never places orders and does not require wallet access.

## What it does

1. Monitors open Predict markets and their orderbook-derived probability.
2. Detects 15-minute and 1-hour probability moves.
3. Detects unusual volume, liquidity, and spread changes.
4. Sends cooldown-protected Bark and Telegram alerts.
5. Provides a live read-only dashboard and a Codex deployment skill.

## Quick start on Ubuntu

```bash
git clone https://github.com/lionman888/predict-pulse.git
cd predict-pulse
sudo PREDICT_API_KEY='your-key' BARK_KEY='optional-bark-key' bash deploy/install.sh
```

Add the Nginx location from `deploy/nginx-location.conf`, then open `/pulse/` on your server.

## Codex

Install the skill from `skill/predict-pulse`. In Codex, ask:

> Use $predict-pulse to deploy this on my VPS with Bark alerts.

Codex becomes the setup and operations interface; a separate UI is optional.

## Development

```bash
PYTHONPATH=. python3 -m unittest -v predict_pulse.test_pulse
```

API reference: https://dev.predict.fun/
