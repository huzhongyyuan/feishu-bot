#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
PORT="${PORT:-8000}"

if [[ ! -x "${PYTHON}" ]]; then
    echo "虚拟环境不存在，请先在项目根目录创建 .venv 并安装 requirements.txt"
    exit 1
fi

cd "${SCRIPT_DIR}"

nohup "${PYTHON}" -m uvicorn main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    > fastapi.log 2>&1 &

echo $! > fastapi.pid
echo "FastAPI started PID=$(cat fastapi.pid), PORT=${PORT}"
