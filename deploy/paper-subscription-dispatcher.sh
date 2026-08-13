#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
APP_DIR="${FEISHU_BOT_APP_DIR:-${PROJECT_DIR}/feishu_bot}"
PYTHON="${FEISHU_BOT_PYTHON:-${PROJECT_DIR}/.venv/bin/python}"
LOG_FILE="${APP_DIR}/subscription-dispatcher.log"
LOCK_FILE="/tmp/feishu-paper-subscription-dispatcher.lock"

exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

cd "${APP_DIR}"
"${PYTHON}" -u subscription_dispatcher.py >>"${LOG_FILE}" 2>&1
