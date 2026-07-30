#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/workspace/feishu_bot"
PID_FILE="${APP_DIR}/fastapi.pid"
LOCK_FILE="/tmp/feishu-bot-watchdog.lock"

exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

if curl --fail --silent --max-time 10 http://127.0.0.1:8000/health >/dev/null; then
    exit 0
fi

if [[ -f "${PID_FILE}" ]]; then
    OLD_PID="$(cat "${PID_FILE}")"
    if [[ "${OLD_PID}" =~ ^[0-9]+$ ]] && kill -0 "${OLD_PID}" 2>/dev/null; then
        kill "${OLD_PID}" 2>/dev/null || true
        for _ in 1 2 3 4 5; do
            kill -0 "${OLD_PID}" 2>/dev/null || break
            sleep 1
        done
    fi
fi

cd "${APP_DIR}"
PORT=8000 ./start.sh
