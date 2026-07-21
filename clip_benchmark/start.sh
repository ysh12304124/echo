#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}"
export CLIP_DEMO_MODEL_PATH="${CLIP_DEMO_MODEL_PATH:-/home/realmagic/models/chinese-clip-vit-base-patch16-fp16}"
export CLIP_DEMO_IMAGE_ROOT="${CLIP_DEMO_IMAGE_ROOT:-$ROOT_DIR/images}"
export CLIP_DEMO_DEFAULT_QUANTIZATION="${CLIP_DEMO_DEFAULT_QUANTIZATION:-nf4}"

mkdir -p "$ROOT_DIR/run" "$ROOT_DIR/log"
echo "$$" > "$ROOT_DIR/run/server.pid"

exec .venv/bin/uvicorn app.main:app \
  --host "${CLIP_DEMO_HOST:-0.0.0.0}" \
  --port "${CLIP_DEMO_PORT:-8400}" \
  --no-access-log
