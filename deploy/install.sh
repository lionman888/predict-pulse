#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi
if [[ -z ${PREDICT_API_KEY:-} ]]; then
  if [[ -s /etc/predict-pulse/api_key ]]; then
    PREDICT_API_KEY=$(< /etc/predict-pulse/api_key)
  elif [[ -t 0 ]]; then
    read -rsp "Predict API key: " PREDICT_API_KEY
    echo
  else
    echo "Set PREDICT_API_KEY when running non-interactively." >&2
    exit 1
  fi
fi

SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx python3-venv rsync
id predictpulse >/dev/null 2>&1 || useradd --system --home /nonexistent --shell /usr/sbin/nologin predictpulse

install -d -m 755 /opt/predict-pulse /etc/predict-pulse
install -d -o predictpulse -g predictpulse -m 750 /var/lib/predict-pulse
chown -R predictpulse:predictpulse /var/lib/predict-pulse
rsync -a --delete --exclude '.git' --exclude '.venv' --exclude 'output' --exclude '.playwright-cli' "$SOURCE_DIR/" /opt/predict-pulse/
python3 -m venv /opt/predict-pulse/.venv
/opt/predict-pulse/.venv/bin/pip install --quiet --upgrade pip
/opt/predict-pulse/.venv/bin/pip install --quiet -r /opt/predict-pulse/requirements.txt
printf '%s' "$PREDICT_API_KEY" > /etc/predict-pulse/api_key

python3 - "$SOURCE_DIR/config.example.json" <<'PY'
import json, os, sys
source=sys.argv[1]; target='/etc/predict-pulse/config.json'
d=json.load(open(target if os.path.exists(target) else source)); d['api_key_file']='/etc/predict-pulse/api_key'
if os.getenv('BARK_KEY'):
    d['notifications']['bark']['enabled']=True
d['notifications']['bark']['key_file']='/etc/predict-pulse/bark_key'
d['notifications']['bark'].pop('key_env_file',None); d['notifications']['bark'].pop('key_name',None)
if os.getenv('TELEGRAM_TOKEN') and os.getenv('TELEGRAM_CHAT_ID'):
    d['notifications']['telegram']['enabled']=True
d['notifications']['telegram']['token_file']='/etc/predict-pulse/telegram_token'
if os.getenv('TELEGRAM_CHAT_ID'):
    d['notifications']['telegram']['chat_id']=os.environ['TELEGRAM_CHAT_ID']
open(target,'w').write(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
PY
[[ -z ${BARK_KEY:-} ]] || printf '%s' "$BARK_KEY" > /etc/predict-pulse/bark_key
[[ -z ${TELEGRAM_TOKEN:-} ]] || printf '%s' "$TELEGRAM_TOKEN" > /etc/predict-pulse/telegram_token
chown -R root:predictpulse /etc/predict-pulse
chmod 750 /etc/predict-pulse
chmod 640 /etc/predict-pulse/*

cp "$SOURCE_DIR/deploy/predict-pulse.service" "$SOURCE_DIR/deploy/predict-pulse-web.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable predict-pulse predict-pulse-web
systemctl restart predict-pulse predict-pulse-web
sleep 3
systemctl is-active --quiet predict-pulse predict-pulse-web
echo "Predict Pulse installed. Dashboard listens on 127.0.0.1:8091."
