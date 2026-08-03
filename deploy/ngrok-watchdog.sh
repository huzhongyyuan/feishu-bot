#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/workspace/feishu_bot"
LOG_FILE="/workspace/ngrok.log"
LOCK_FILE="/tmp/ngrok-watchdog.lock"

exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

if pgrep -f "^ngrok http 8000" >/dev/null \
    && curl --fail --silent --max-time 5 http://127.0.0.1:4040/api/tunnels \
        | grep -q '"public_url"'; then
    exit 0
fi

pkill -f "^ngrok http 8000" 2>/dev/null || true

cd "${APP_DIR}"
nohup env \
    http_proxy=http://127.0.0.1:7890 \
    https_proxy=http://127.0.0.1:7890 \
    ngrok http 8000 --log=stdout --log-format=json \
    > "${LOG_FILE}" 2>&1 &
