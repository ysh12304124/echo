#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p log

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "clip virtual environment is missing; run ./setup.sh first" >&2
  exit 1
fi

if [[ -f log/clip.pid ]] && kill -0 "$(cat log/clip.pid)" 2>/dev/null; then
  echo "clip service is already running (PID $(cat log/clip.pid))"
  exit 0
fi

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}"
export PYTHONPATH="$PWD"
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${CLIP_PORT:-8300}" \
  >> log/clip.log 2>&1 &
echo $! > log/clip.pid
echo "clip service started (PID $(cat log/clip.pid)); log: log/clip.log"
