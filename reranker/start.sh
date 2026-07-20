#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p log

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "reranker virtual environment is missing; run ./setup.sh first" >&2
  exit 1
fi

if [[ -f log/reranker.pid ]] && kill -0 "$(cat log/reranker.pid)" 2>/dev/null; then
  echo "reranker is already running (PID $(cat log/reranker.pid))"
  exit 0
fi

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}"
export PYTHONPATH="$PWD"
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${RERANKER_PORT:-8200}" \
  >> log/reranker.log 2>&1 &
echo $! > log/reranker.pid
echo "reranker started (PID $(cat log/reranker.pid)); log: log/reranker.log"
