#!/usr/bin/env bash
# 启动 Echo 算力服务：默认以 nohup 后台方式运行，日志只写一份 log/compute.log。
#
# uvicorn 自身的启动横幅/异常输出也直接追加进 log/compute.log（而不是单独的
# uvicorn.out），保证一个服务只对应一份日志文件。
#
# 用法: ./start.sh              启动(默认端口 8100)
#       COMPUTE_PORT=8101 ./start.sh
#       ./stop.sh                停止
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "[compute] 未找到虚拟环境 .venv，请先执行: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

mkdir -p log
PORT="${COMPUTE_PORT:-8100}"
PID_FILE="log/compute.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "[compute] 已有进程在运行 (PID $(cat "$PID_FILE"))，先执行 ./stop.sh 再启动，或忽略本次启动。"
  exit 1
fi

nohup uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --reload >> log/compute.log 2>&1 &
PID=$!
disown
echo "$PID" > "$PID_FILE"

echo "[compute] 已在后台启动 (PID $PID)，端口 $PORT"
echo "[compute] 日志: log/compute.log"
echo "[compute] 健康检查: curl http://127.0.0.1:$PORT/health"
echo "[compute] 停止: ./stop.sh"
