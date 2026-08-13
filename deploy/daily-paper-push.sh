#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
APP_DIR="${FEISHU_BOT_APP_DIR:-${PROJECT_DIR}/feishu_bot}"
PYTHON="${FEISHU_BOT_PYTHON:-${PROJECT_DIR}/.venv/bin/python}"
LOG_FILE="${APP_DIR}/daily-push.log"
LOCK_FILE="/tmp/feishu-daily-paper.lock"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    exit 0
fi

cd "${APP_DIR}"
{
    printf '[%s] daily paper push started\n' "$(date '+%F %T %Z')"
    "${PYTHON}" -u daily_paper.py
    printf '[%s] daily paper push finished\n' "$(date '+%F %T %Z')"
} >>"${LOG_FILE}" 2>&1
