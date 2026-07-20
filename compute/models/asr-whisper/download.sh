#!/usr/bin/env bash
# 预下载/缓存 faster-whisper 模型权重(CTranslate2 格式，来自 HuggingFace)，
# 避免第一次 start.sh 时才现场下载。可重复执行，已缓存则秒过。
#
# 默认走国内镜像 hf-mirror.com(直连 huggingface.co 在国内经常很慢/超时)。
# 如需换回官方源: HF_ENDPOINT=https://huggingface.co ./download.sh
#
# 用法: ./download.sh [模型规格]   默认 medium
#       WHISPER_MODEL_SIZE=large-v3 ./download.sh
set -euo pipefail
cd "$(dirname "$0")"

MODEL_SIZE="${1:-${WHISPER_MODEL_SIZE:-medium}}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

if [ ! -d .venv ]; then
  echo "[asr] 创建虚拟环境 .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "[asr] 下载/缓存模型: $MODEL_SIZE (镜像: $HF_ENDPOINT，存到 ./weights，可能需要几分钟，模型越大越久)"
# 注意: 必须用 cache_dir(不是 output_dir)，跟 server.py 里 WhisperModel(download_root=...) 内部
# 走的是同一套 cache_dir 缓存布局，否则 download.sh 预热的缓存 start.sh 时对不上、又得重新下一遍。
python3 - <<PY
from faster_whisper.utils import download_model, _MODELS
repo_id = _MODELS.get("$MODEL_SIZE", "$MODEL_SIZE")
print(f"实际拉取的 HuggingFace 仓库: {repo_id}")
path = download_model("$MODEL_SIZE", cache_dir="./weights")
print(f"模型已缓存到: {path}")
PY

echo "[asr] 完成。上面打印的仓库名/路径应包含 \"$MODEL_SIZE\"，如与预期不符请截图反馈。"
echo "[asr] 执行 ./start.sh 启动服务(默认端口 8081)。"
