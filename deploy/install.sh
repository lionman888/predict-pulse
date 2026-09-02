#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi
if [[ -z ${PREDICT_API_KEY:-} ]]; then
  echo "Set PREDICT_API_KEY before running." >&2
  exit 1
fi

SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx python3-flask python3-pip
python3 -m pip install --break-system-packages 'websockets>=13,<17'

install -d -m 755 /opt/predict-pulse /etc/predict-pulse
install -d -m 700 /var/lib/predict-pulse /root/.config/predict-pulse
cp -a "$SOURCE_DIR/predict_pulse" "$SOURCE_DIR/web" "$SOURCE_DIR/web.py" /opt/predict-pulse/
printf '%s' "$PREDICT_API_KEY" > /root/.config/predict-pulse/api_key
chmod 600 /root/.config/predict-pulse/api_key

python3 - "$SOURCE_DIR/config.example.json" <<'PY'
import json, os, sys
source=sys.argv[1]; target='/etc/predict-pulse/config.json'
d=json.load(open(source)); d['api_key_file']='/root/.config/predict-pulse/api_key'
d['notifications']['bark']['enabled']=bool(os.getenv('BARK_KEY'))
d['notifications']['bark']['key_file']='/root/.config/predict-pulse/bark_key'
d['notifications']['bark'].pop('key_env_file',None); d['notifications']['bark'].pop('key_name',None)
d['notifications']['telegram']['enabled']=bool(os.getenv('TELEGRAM_TOKEN') and os.getenv('TELEGRAM_CHAT_ID'))
d['notifications']['telegram']['token_file']='/root/.config/predict-pulse/telegram_token'
d['notifications']['telegram']['chat_id']=os.getenv('TELEGRAM_CHAT_ID','')
open(target,'w').write(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
PY
[[ -z ${BARK_KEY:-} ]] || printf '%s' "$BARK_KEY" > /root/.config/predict-pulse/bark_key
[[ -z ${TELEGRAM_TOKEN:-} ]] || printf '%s' "$TELEGRAM_TOKEN" > /root/.config/predict-pulse/telegram_token
chmod 600 /etc/predict-pulse/config.json /root/.config/predict-pulse/*

cp "$SOURCE_DIR/deploy/predict-pulse.service" "$SOURCE_DIR/deploy/predict-pulse-web.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now predict-pulse predict-pulse-web
echo "Predict Pulse installed. Dashboard listens on 127.0.0.1:8091."
