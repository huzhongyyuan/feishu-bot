#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/workspace/feishu_bot"
PORT=8000

echo "==> 进入项目目录"
cd ${APP_DIR}

echo "==> 停止旧服务"
pkill -f "uvicorn" || true
pkill -f "cloudflared" || true

echo "==> 检查依赖"

command -v python3 >/dev/null || {
    echo "缺少 python3"
    exit 1
}

command -v cloudflared >/dev/null || {
    echo "缺少 cloudflared"
    exit 1
}


echo "==> 启动 FastAPI"

nohup python3 -m uvicorn main:app \
--host 0.0.0.0 \
--port ${PORT} \
> /workspace/fastapi.log 2>&1 &


sleep 5


echo "==> 健康检查"

curl --fail \
http://127.0.0.1:${PORT}/health \
|| {
    echo "FastAPI启动失败"
    tail -50 /workspace/fastapi.log
    exit 1
}


echo "==> 启动 Cloudflare Tunnel"

nohup cloudflared tunnel \
--protocol http2 \
--url http://127.0.0.1:${PORT} \
> /workspace/cloudflared.log 2>&1 &


sleep 8


URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' \
/workspace/cloudflared.log | tail -1)


if [ -z "$URL" ]; then
    echo "Tunnel启动失败"
    tail -100 /workspace/cloudflared.log
    exit 1
fi


echo
echo "=============================="
echo "部署完成"
echo
echo "公网地址:"
echo "$URL"
echo
echo "健康检查:"
echo "$URL/health"
echo
echo "飞书回调:"
echo "$URL/webhook"
echo "=============================="
