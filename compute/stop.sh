#!/usr/bin/env bash
# 停止 start.sh 启动的 Echo 算力服务。
set -euo pipefail
cd "$(dirname "$0")"

PID_FILE="log/compute.pid"
if [ ! -f "$PID_FILE" ]; then
  echo "[compute] 未找到 $PID_FILE，可能没有通过 start.sh 启动，或已停止。"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "[compute] 已发送停止信号 (PID $PID)"
else
  echo "[compute] 进程 $PID 已不存在"
fi
rm -f "$PID_FILE"
