#!/usr/bin/env bash

LOG_FILE="/workspace/feishu_bot/fastapi.log"

while true; do
    echo
    echo "========== 定时检查 $(date '+%F %T') =========="
    echo "目录：$(pwd)"
    uptime

    echo "--- 服务状态 ---"
    pgrep -af 'uvicorn main:app' || echo "uvicorn 未运行"

    echo "--- 最近 30 行日志 ---"
    if [ -f "$LOG_FILE" ]; then
        tail -n 30 "$LOG_FILE"
    else
        echo "日志不存在：$LOG_FILE"
    fi

    echo "下次检查：30 分钟后"
    sleep 1800
done
