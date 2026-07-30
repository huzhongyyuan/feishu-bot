#!/usr/bin/env bash
set -Eeuo pipefail

DISPLAY_NUMBER=":99"
SCREEN_SIZE="1440x900x24"
APP_DIR="/workspace/feishu_bot"
PROFILE_DIR="${APP_DIR}/state/chatgpt-browser"
CHROMIUM_BIN="/root/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome"
NOVNC_WEB_ROOT="/usr/share/novnc"

mkdir -p "${PROFILE_DIR}"
chmod 700 "${PROFILE_DIR}"

if ! pgrep -f "^Xvfb ${DISPLAY_NUMBER} " >/dev/null; then
    nohup Xvfb "${DISPLAY_NUMBER}" \
        -screen 0 "${SCREEN_SIZE}" \
        -nolisten tcp \
        > /workspace/chatgpt-xvfb.log 2>&1 &
    sleep 1
fi

export DISPLAY="${DISPLAY_NUMBER}"

if ! pgrep -f "^openbox --startup " >/dev/null; then
    nohup openbox --startup "xsetroot -solid '#202124'" \
        > /workspace/chatgpt-openbox.log 2>&1 &
fi

if ! pgrep -f "^x11vnc -display ${DISPLAY_NUMBER} " >/dev/null; then
    nohup x11vnc \
        -display "${DISPLAY_NUMBER}" \
        -localhost \
        -forever \
        -shared \
        -nopw \
        > /workspace/chatgpt-x11vnc.log 2>&1 &
fi

if ! pgrep -f "^websockify .*127\\.0\\.0\\.1:6080 " >/dev/null; then
    nohup websockify \
        --web "${NOVNC_WEB_ROOT}" \
        127.0.0.1:6080 \
        127.0.0.1:5900 \
        > /workspace/chatgpt-novnc.log 2>&1 &
fi

if ! pgrep -f "^${CHROMIUM_BIN} .*--user-data-dir=${PROFILE_DIR}" >/dev/null; then
    nohup "${CHROMIUM_BIN}" \
        --no-sandbox \
        --no-first-run \
        --no-default-browser-check \
        --disable-dev-shm-usage \
        --disable-gpu \
        --proxy-server=http://127.0.0.1:7890 \
        --user-data-dir="${PROFILE_DIR}" \
        --remote-debugging-address=127.0.0.1 \
        --remote-debugging-port=9222 \
        --window-size=1400,850 \
        https://chatgpt.com/ \
        > /workspace/chatgpt-chromium.log 2>&1 &
fi
