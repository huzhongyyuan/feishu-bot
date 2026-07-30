#!/bin/sh
set -eu

MIHOMO_BIN="${MIHOMO_BIN:-/usr/local/bin/mihomo}"
MIHOMO_DIR="${MIHOMO_DIR:-/etc/mihomo}"
MIHOMO_LOG="${MIHOMO_LOG:-/var/log/mihomo.log}"
LOCK_FILE="${MIHOMO_LOCK_FILE:-/tmp/mihomo-watchdog.lock}"

exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

if pgrep -x mihomo >/dev/null 2>&1; then
    exit 0
fi

if [ ! -x "$MIHOMO_BIN" ] || [ ! -r "$MIHOMO_DIR/config.yaml" ]; then
    echo "mihomo binary or config is missing" >&2
    exit 1
fi

nohup "$MIHOMO_BIN" -d "$MIHOMO_DIR" >>"$MIHOMO_LOG" 2>&1 &
