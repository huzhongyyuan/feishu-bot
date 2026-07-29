#!/bin/bash

cd /workspace/feishu_bot

nohup python3 -m uvicorn main:app \
--host 0.0.0.0 \
--port 8000 \
> fastapi.log 2>&1 &

echo $! > fastapi.pid

echo "FastAPI started PID=$(cat fastapi.pid)"
