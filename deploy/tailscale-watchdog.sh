#!/usr/bin/env bash
set -Eeuo pipefail

TAILSCALED="/usr/sbin/tailscaled"
TAILSCALE="/usr/bin/tailscale"
STATE_FILE="/var/lib/tailscale/tailscaled.state"
SOCKET_FILE="/var/run/tailscale/tailscaled.sock"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
LOG_FILE="${TAILSCALE_WATCHDOG_LOG:-${PROJECT_DIR}/tailscale-watchdog.log}"
HEALTH_FILE="/run/tailscale-watchdog.ok"
LOCK_FILE="/tmp/tailscale-watchdog.lock"
KEEPALIVE_PEER="${TAILSCALE_KEEPALIVE_PEER:-100.99.47.12}"

exec 9>"${LOCK_FILE}"
flock -n 9 || exit 0

if [[ -f "${LOG_FILE}" ]] && (( $(stat -c %s "${LOG_FILE}") > 1048576 )); then
    tail -n 1000 "${LOG_FILE}" >"${LOG_FILE}.tmp"
    mv "${LOG_FILE}.tmp" "${LOG_FILE}"
fi

log_event() {
    printf '%s %s\n' "$(date -Is)" "$*" >>"${LOG_FILE}"
}

backend_running() {
    timeout 8 "${TAILSCALE}" status --json 2>/dev/null \
        | grep -Eq '"BackendState"[[:space:]]*:[[:space:]]*"Running"'
}

if ! pgrep -x tailscaled >/dev/null || ! backend_running; then
    log_event "Tailscale unhealthy; restarting userspace daemon"
    pkill -x tailscaled 2>/dev/null || true
    for _ in 1 2 3 4 5; do
        pgrep -x tailscaled >/dev/null || break
        sleep 1
    done
    if ! pgrep -x tailscaled >/dev/null; then
        rm -f "${SOCKET_FILE}"
    fi
    mkdir -p "$(dirname "${STATE_FILE}")" "$(dirname "${SOCKET_FILE}")"
    nohup "${TAILSCALED}" \
        --state="${STATE_FILE}" \
        --tun=userspace-networking \
        >>"${LOG_FILE}" 2>&1 &

    for _ in 1 2 3 4 5 6; do
        sleep 2
        backend_running && break
    done

    if ! backend_running; then
        log_event "Tailscale restart did not reach Running state"
        exit 1
    fi
    log_event "Tailscale restored"
fi

# One server-originated disco ping keeps the DERP/direct peer path warm.
if ! timeout 12 "${TAILSCALE}" ping \
    --c 1 --until-direct=false --timeout 8s "${KEEPALIVE_PEER}" \
    >/dev/null 2>&1; then
    log_event "Keepalive peer ${KEEPALIVE_PEER} did not respond"
fi

touch "${HEALTH_FILE}"
