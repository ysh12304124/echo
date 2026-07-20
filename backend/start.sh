#!/usr/bin/env bash
# 启动 Echo 后台服务：默认以 nohup 后台方式运行，日志只写一份 log/echo.log。
#
# 说明：app/main.py 里的请求日志中间件已经把每个请求/响应都记进了 log/echo.log，
# 这里再加 --no-access-log 关掉 uvicorn 自带的访问日志，避免重复一遍；同时把
# uvicorn 自身的启动横幅/异常输出也直接追加进 log/echo.log（而不是单独的
# uvicorn.out/uvicorn.log），保证一个服务只对应一份日志文件。
#
# 用法: ./start.sh            启动(默认端口 8000)
#       ECHO_PORT=8001 ./start.sh
#       ./stop.sh              停止
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "[backend] 未找到虚拟环境 .venv，请先执行: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

mkdir -p log
PORT="${ECHO_PORT:-8000}"
PID_FILE="log/backend.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "[backend] 已有进程在运行 (PID $(cat "$PID_FILE"))，先执行 ./stop.sh 再启动，或忽略本次启动。"
  exit 1
fi

nohup uvicorn app.main:app --reload --host 0.0.0.0 --port "$PORT" --no-access-log >> log/echo.log 2>&1 &
PID=$!
disown
echo "$PID" > "$PID_FILE"

echo "[backend] 已在后台启动 (PID $PID)，端口 $PORT"
echo "[backend] 日志: log/echo.log"
echo "[backend] 健康检查: curl http://127.0.0.1:$PORT/health"
echo "[backend] 停止: ./stop.sh"
