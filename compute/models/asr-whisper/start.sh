#!/usr/bin/env bash
# 启动 Whisper ASR 服务(OpenAI 兼容 /v1/audio/transcriptions)，默认端口 8081。
# 默认以 nohup 后台方式运行(不会占住终端)，日志只写一份 log/asr.log，风格与
# backend/compute 的 start.sh 一致，不会额外产生 uvicorn.log/uvicorn.out。
#
# 首次运行会自动建虚拟环境+装依赖；模型权重建议先跑一次 ./download.sh 预热，
# 否则第一次启动时会现场下载(需要能访问 HuggingFace)。
#
# 可通过环境变量调整(3090/有 GPU 时建议 WHISPER_DEVICE=cuda WHISPER_COMPUTE_TYPE=float16)：
#   WHISPER_MODEL_SIZE   模型规格，默认 medium(tiny/base/small/medium/large-v3 可选，越大越准越慢)
#   WHISPER_DEVICE       auto|cuda|cpu，默认 auto(自动探测有没有可用 GPU)
#   WHISPER_COMPUTE_TYPE default|float16|int8|int8_float16，默认 default(按设备自动选)
#   WHISPER_PORT         监听端口，默认 8081
#   HF_ENDPOINT          模型未缓存时现场下载走的镜像，默认国内镜像 hf-mirror.com
#
# 用法: ./start.sh    启动(后台)     ./stop.sh   停止
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "[asr] 未找到虚拟环境，先执行一次初始化(等价于 download.sh 的装依赖部分)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export WHISPER_MODEL_SIZE="${WHISPER_MODEL_SIZE:-medium}"
export WHISPER_DEVICE="${WHISPER_DEVICE:-auto}"
export WHISPER_COMPUTE_TYPE="${WHISPER_COMPUTE_TYPE:-default}"
WHISPER_PORT="${WHISPER_PORT:-8081}"

mkdir -p log
PID_FILE="log/asr.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "[asr] 已有进程在运行 (PID $(cat "$PID_FILE"))，先执行 ./stop.sh 再启动，或忽略本次启动。"
  exit 1
fi

nohup uvicorn server:app --host 0.0.0.0 --port "$WHISPER_PORT" >> log/asr.log 2>&1 &
PID=$!
disown
echo "$PID" > "$PID_FILE"

echo "[asr] 已在后台启动 (PID $PID) model=$WHISPER_MODEL_SIZE device=$WHISPER_DEVICE compute_type=$WHISPER_COMPUTE_TYPE port=$WHISPER_PORT"
echo "[asr] 日志: log/asr.log (模型加载较慢，健康检查前先 tail -f log/asr.log 看是否加载完成)"
echo "[asr] 健康检查: curl http://127.0.0.1:$WHISPER_PORT/health"
echo "[asr] 停止: ./stop.sh"
