#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EMOTION_MODEL="$MODEL_DIR/model.safetensors"
EMOTION_SHA256="48acf03b1fd90ea45c5e91eb3be2f364cee1c1342639962bd4eae1eac2ad2f93"
EMOTION_URL="https://huggingface.co/trpakov/vit-face-expression/resolve/ef0bc6fc34241b6587e7e009e7711357be28c024/model.safetensors?download=true"

verify_sha256() {
  local file="$1"
  local expected="$2"
  local actual
  actual="$(sha256sum "$file" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]]
}

if [[ -f "$EMOTION_MODEL" ]] && verify_sha256 "$EMOTION_MODEL" "$EMOTION_SHA256"; then
  echo "Face-expression weight already verified: $EMOTION_MODEL"
else
  temporary="$EMOTION_MODEL.part"
  rm -f "$temporary"
  echo "Downloading face-expression weight to $EMOTION_MODEL"
  curl --fail --location --retry 3 --output "$temporary" "$EMOTION_URL"
  if ! verify_sha256 "$temporary" "$EMOTION_SHA256"; then
    rm -f "$temporary"
    echo "SHA256 verification failed for face-expression weight" >&2
    exit 1
  fi
  mv "$temporary" "$EMOTION_MODEL"
fi

# The protocol leaves the VLM implementation open. Set an explicit Ollama model
# when the implementation is selected, for example:
#   OLLAMA_VLM_MODEL=gemma3:4b ./download_time_models.sh
if [[ -n "${OLLAMA_VLM_MODEL:-}" ]]; then
  if ! command -v ollama >/dev/null 2>&1; then
    echo "OLLAMA_VLM_MODEL is set but the ollama command is unavailable" >&2
    exit 1
  fi
  echo "Downloading VLM through Ollama: $OLLAMA_VLM_MODEL"
  ollama pull "$OLLAMA_VLM_MODEL"
else
  echo "VLM download skipped: set OLLAMA_VLM_MODEL after selecting the protocol implementation"
fi
