#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="${CLIP_SOURCE_DIR:-/home/realmagic/models/chinese-clip-vit-base-patch16-source}"
BASE_URL="https://modelscope.cn/models/AI-ModelScope/chinese-clip-vit-base-patch16/resolve/master"
mkdir -p "$SOURCE_DIR"

download() {
  local name="$1"
  curl -fL --retry 5 --continue-at - --output "$SOURCE_DIR/$name" "$BASE_URL/$name"
}

download config.json
download preprocessor_config.json
download vocab.txt
download pytorch_model.bin

echo "7b7b583c210c867410bc6bdb8a55fe14eec62999e0a9ea31ff222dc501f9cfbe  $SOURCE_DIR/pytorch_model.bin" | sha256sum --check --status
echo "official Chinese-CLIP source checkpoint verified"
