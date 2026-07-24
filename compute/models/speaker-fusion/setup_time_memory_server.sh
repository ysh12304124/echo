#!/usr/bin/env bash
#
# 在 192.168.0.100 上离线准备 Echo time_memory.py 的运行资源。
# 本脚本不会访问互联网，也不会执行 pip/conda 下载。
#
# 默认行为：
#   1. 自动识别 echo/compute；
#   2. 将现有资源放入 echo/compute/models/speaker-fusion；
#   3. 复用服务器已有的 speaker-fusion Conda 环境；
#   4. 生成 .time_memory_env，供服务启动或手工调试时 source；
#   5. 检查模型文件、Python 库、CUDA 和 FFmpeg。
#
# 用法：
#   bash setup_time_memory_server.sh
#   bash setup_time_memory_server.sh --compute-dir /path/to/echo/compute
#   bash setup_time_memory_server.sh --link
#   bash setup_time_memory_server.sh --env clone
#   bash setup_time_memory_server.sh --verify-only
#
# 可覆盖的服务器源目录：
#   SERVER_MODELS_ROOT=/home/realmagic/models/speaker-fusion
#   SERVER_LRASD_ROOT=/home/realmagic/vendor/speaker-fusion/LR-ASD
#   SERVER_PYTHON=/home/realmagic/miniconda3/envs/speaker-fusion/bin/python
#
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
  pwd -P
)"

COMPUTE_DIR="${ECHO_COMPUTE_DIR:-}"
PROJECT_DIR="${PROJECT_DIR:-}"
MODEL_DIR="${TIME_MEMORY_MODEL_DIR:-}"
LRASD_DIR="${TIME_MEMORY_LRASD_DIR:-}"
RESOURCE_MODE="${RESOURCE_MODE:-copy}"
ENV_MODE="${ENV_MODE:-reuse}"
FORCE="${FORCE:-0}"
VERIFY_ONLY=0

SERVER_MODELS_ROOT="${SERVER_MODELS_ROOT:-/home/realmagic/models/speaker-fusion}"
SERVER_LRASD_ROOT="${SERVER_LRASD_ROOT:-/home/realmagic/vendor/speaker-fusion/LR-ASD}"
SERVER_PYTHON="${SERVER_PYTHON:-/home/realmagic/miniconda3/envs/speaker-fusion/bin/python}"
SERVER_CONDA="${SERVER_CONDA:-/home/realmagic/miniconda3/bin/conda}"

usage() {
  cat <<'EOF'
用法：
  bash setup_time_memory_server.sh [选项]

选项：
  --compute-dir DIR   Echo 的 compute 目录；通常可自动识别
  --project-dir DIR   time_memory.py 所在目录；默认 compute/app/analyze
  --models-dir DIR    模型目标目录；默认 compute/models/speaker-fusion
  --copy              复制模型文件到工程（默认，复制时解析缓存软链接）
  --link              只在工程中建立资源软链接，速度快且不占重复空间
  --env reuse         复用现有 speaker-fusion Conda 环境（默认）
  --env clone         离线克隆现有 Conda 环境到工程 .runtime/conda
  --force             目标存在但不完整时，先备份再重新准备
  --verify-only       不复制，只验证工程现有资源与运行环境
  -h, --help          显示帮助

示例：
  bash setup_time_memory_server.sh \
    --compute-dir /home/realmagic/echo/compute

说明：
  本脚本没有 wget、curl、git clone 或 pip install，不会联网下载。
  脚本可放在 compute/models 或 compute/models/speaker-fusion 中运行。
  ASR、VAD、PUNC、Pyannote 和 LR-ASD 都放入：
    compute/models/speaker-fusion/
  默认复制模型但复用 Python 环境。若需要工程完全独立的依赖环境，
  使用 --env clone；该操作会占用较多磁盘空间，但仍然不联网。
EOF
}

die() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[time-memory-setup] %s\n' "$*"
}

while (($# > 0)); do
  case "$1" in
    --compute-dir)
      (($# >= 2)) || die "--compute-dir 缺少目录参数"
      COMPUTE_DIR="$2"
      shift 2
      ;;
    --project-dir)
      (($# >= 2)) || die "--project-dir 缺少目录参数"
      PROJECT_DIR="$2"
      shift 2
      ;;
    --models-dir)
      (($# >= 2)) || die "--models-dir 缺少目录参数"
      MODEL_DIR="$2"
      shift 2
      ;;
    --copy)
      RESOURCE_MODE="copy"
      shift
      ;;
    --link)
      RESOURCE_MODE="link"
      shift
      ;;
    --env)
      (($# >= 2)) || die "--env 缺少 reuse 或 clone"
      ENV_MODE="$2"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --verify-only)
      VERIFY_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "未知参数：$1（使用 --help 查看用法）"
      ;;
  esac
done

case "$RESOURCE_MODE" in
  copy|link) ;;
  *) die "RESOURCE_MODE 只能是 copy 或 link：$RESOURCE_MODE" ;;
esac

case "$ENV_MODE" in
  reuse|clone) ;;
  *) die "ENV_MODE 只能是 reuse 或 clone：$ENV_MODE" ;;
esac

detect_compute_dir() {
  local candidate=""
  local script_parent=""
  local git_root=""

  if [[ -n "$COMPUTE_DIR" ]]; then
    printf '%s\n' "$COMPUTE_DIR"
    return 0
  fi

  # 脚本位于 compute/models/。
  if [[ "$(basename -- "$SCRIPT_DIR")" == "models" ]]; then
    candidate="$(dirname -- "$SCRIPT_DIR")"
    [[ -d "$candidate/app" ]] && {
      printf '%s\n' "$candidate"
      return 0
    }
  fi

  # 脚本位于 compute/models/speaker-fusion/。
  script_parent="$(dirname -- "$SCRIPT_DIR")"
  if [[ "$(basename -- "$script_parent")" == "models" ]]; then
    candidate="$(dirname -- "$script_parent")"
    [[ -d "$candidate/app" ]] && {
      printf '%s\n' "$candidate"
      return 0
    }
  fi

  # 脚本直接位于 compute/。
  if [[ -d "$SCRIPT_DIR/app" && -d "$SCRIPT_DIR/models" ]]; then
    printf '%s\n' "$SCRIPT_DIR"
    return 0
  fi

  # 最后尝试从 Git 仓库根目录识别 echo/compute。
  if command -v git >/dev/null 2>&1; then
    git_root="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
    if [[ -n "$git_root" && -d "$git_root/compute/app" ]]; then
      printf '%s\n' "$git_root/compute"
      return 0
    fi
  fi

  return 1
}

if detected_compute="$(detect_compute_dir)"; then
  COMPUTE_DIR="$(realpath -m -- "$detected_compute")"
elif [[ -n "$COMPUTE_DIR" ]]; then
  COMPUTE_DIR="$(realpath -m -- "$COMPUTE_DIR")"
else
  COMPUTE_DIR=""
fi

if [[ -z "$PROJECT_DIR" ]]; then
  if [[ -n "$COMPUTE_DIR" ]]; then
    PROJECT_DIR="$COMPUTE_DIR/app/analyze"
  else
    PROJECT_DIR="$SCRIPT_DIR"
  fi
fi

if [[ -z "$MODEL_DIR" ]]; then
  if [[ -n "$COMPUTE_DIR" ]]; then
    MODEL_DIR="$COMPUTE_DIR/models/speaker-fusion"
  else
    MODEL_DIR="$PROJECT_DIR/models"
  fi
fi

PROJECT_DIR="$(realpath -m -- "$PROJECT_DIR")"
MODEL_DIR="$(realpath -m -- "$MODEL_DIR")"
if [[ -z "$LRASD_DIR" ]]; then
  LRASD_DIR="$MODEL_DIR/LR-ASD"
fi
LRASD_DIR="$(realpath -m -- "$LRASD_DIR")"

[[ -d "$PROJECT_DIR" ]] ||
  die "time_memory 工程目录不存在：$PROJECT_DIR"

# 安装模型不强制要求视觉主程序已经提交到仓库。
# 如果代码存在，末尾会执行额外导入检查；不存在时仍可先准备模型。
if [[ ! -f "$PROJECT_DIR/time_memory.py" ]]; then
  log "警告：暂未找到 $PROJECT_DIR/time_memory.py；仅准备模型资源"
fi
if [[ ! -f "$PROJECT_DIR/speaker_video_pipeline.py" ]]; then
  log "提示：暂未找到 speaker_video_pipeline.py；稍后放入 $PROJECT_DIR 即可"
fi

find_snapshot() {
  local preferred="$1"
  local snapshots_root="$2"
  local result=""

  if [[ -d "$preferred" ]]; then
    printf '%s\n' "$preferred"
    return 0
  fi

  if [[ -d "$snapshots_root" ]]; then
    result="$(
      find "$snapshots_root" -mindepth 1 -maxdepth 1 -type d -print \
        | sort \
        | tail -n 1
    )"
  fi
  [[ -n "$result" && -d "$result" ]] || return 1
  printf '%s\n' "$result"
}

ASR_SOURCE="${ASR_SOURCE:-$SERVER_MODELS_ROOT/modelscope/models/iic--speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch/snapshots/master}"
VAD_SOURCE="${VAD_SOURCE:-$SERVER_MODELS_ROOT/modelscope/models/iic--speech_fsmn_vad_zh-cn-16k-common-pytorch/snapshots/master}"
PUNC_SOURCE="${PUNC_SOURCE:-$SERVER_MODELS_ROOT/modelscope/models/iic--punc_ct-transformer_zh-cn-common-vocab272727-pytorch/snapshots/master}"

PYANNOTE_REPO="$SERVER_MODELS_ROOT/huggingface/hub/models--pyannote--speaker-diarization-community-1"
PYANNOTE_PREFERRED="$PYANNOTE_REPO/snapshots/3533c8cf8e369892e6b79ff1bf80f7b0286a54ee"
if [[ -z "${PYANNOTE_SOURCE:-}" ]]; then
  PYANNOTE_SOURCE="$(
    find_snapshot "$PYANNOTE_PREFERRED" "$PYANNOTE_REPO/snapshots"
  )" || die "找不到服务器现有的 Pyannote community-1 快照"
fi

tree_has_files() {
  local root="$1"
  shift
  local marker
  [[ -d "$root" ]] || return 1
  for marker in "$@"; do
    [[ -f "$root/$marker" ]] || return 1
  done
}

check_source_tree() {
  local label="$1"
  local source="$2"
  shift 2
  tree_has_files "$source" "$@" ||
    die "$label 源目录不存在或文件不完整：$source"
}

# 在开始修改目标目录前一次性验证全部服务器源资源，防止半途失败。
check_source_tree "FunASR ASR" "$ASR_SOURCE" model.pt configuration.json
check_source_tree "FunASR VAD" "$VAD_SOURCE" model.pt configuration.json
check_source_tree "FunASR PUNC" "$PUNC_SOURCE" model.pt configuration.json
check_source_tree \
  "Pyannote community-1" \
  "$PYANNOTE_SOURCE" \
  config.yaml \
  embedding/pytorch_model.bin \
  segmentation/pytorch_model.bin \
  plda/plda.npz
check_source_tree \
  "LR-ASD" \
  "$SERVER_LRASD_ROOT" \
  model/faceDetector/s3fd/__init__.py \
  model/faceDetector/s3fd/sfd_face.pth \
  weight/pretrain_AVA.model

backup_existing() {
  local target="$1"
  local stamp backup
  stamp="$(date +%Y%m%d_%H%M%S)"
  backup="${target}.backup_${stamp}"
  while [[ -e "$backup" || -L "$backup" ]]; do
    backup="${backup}_$RANDOM"
  done
  mv -- "$target" "$backup"
  log "原目标不完整，已备份：$backup"
}

install_tree() {
  local label="$1"
  local source="$2"
  local target="$3"
  shift 3
  local markers=("$@")
  local stage=""

  if tree_has_files "$target" "${markers[@]}"; then
    log "$label 已完整，跳过：$target"
    return 0
  fi

  if ((VERIFY_ONLY)); then
    die "$label 目标目录不存在或文件不完整：$target"
  fi

  if [[ -e "$target" || -L "$target" ]]; then
    if [[ "$FORCE" == "1" ]]; then
      backup_existing "$target"
    else
      die "$label 目标已存在但不完整：$target；检查后使用 --force 重建"
    fi
  fi

  mkdir -p -- "$(dirname -- "$target")"
  if [[ "$RESOURCE_MODE" == "link" ]]; then
    ln -s -- "$source" "$target"
    log "$label 已建立软链接：$target -> $source"
  else
    stage="$(mktemp -d "$(dirname -- "$target")/.time-memory-copy.XXXXXX")"
    mkdir -p -- "$stage/resource"
    # -L 很重要：Hugging Face 快照大量使用指向 blobs 的软链接。
    # 解析软链接后，工程中的模型目录才是可独立搬运的完整副本。
    cp -aL -- "$source/." "$stage/resource/"
    mv -- "$stage/resource" "$target"
    rmdir -- "$stage"
    log "$label 已复制：$source -> $target"
  fi

  tree_has_files "$target" "${markers[@]}" ||
    die "$label 复制后校验失败：$target"
}

install_tree \
  "FunASR ASR" "$ASR_SOURCE" "$MODEL_DIR/asr" \
  model.pt configuration.json
install_tree \
  "FunASR VAD" "$VAD_SOURCE" "$MODEL_DIR/vad" \
  model.pt configuration.json
install_tree \
  "FunASR PUNC" "$PUNC_SOURCE" "$MODEL_DIR/punc" \
  model.pt configuration.json
install_tree \
  "Pyannote community-1" "$PYANNOTE_SOURCE" "$MODEL_DIR/pyannote" \
  config.yaml embedding/pytorch_model.bin segmentation/pytorch_model.bin plda/plda.npz
install_tree \
  "LR-ASD" "$SERVER_LRASD_ROOT" "$LRASD_DIR" \
  model/faceDetector/s3fd/__init__.py \
  model/faceDetector/s3fd/sfd_face.pth \
  weight/pretrain_AVA.model

[[ -x "$SERVER_PYTHON" ]] ||
  die "服务器 Python 不存在或不可执行：$SERVER_PYTHON"

RUNTIME_PYTHON="$SERVER_PYTHON"
if [[ "$ENV_MODE" == "clone" ]]; then
  CLONE_PREFIX="$MODEL_DIR/.runtime/conda"
  if [[ -x "$CLONE_PREFIX/bin/python" ]]; then
    log "工程内 Conda 环境已存在，跳过克隆：$CLONE_PREFIX"
  elif ((VERIFY_ONLY)); then
    die "工程内 Conda 环境不存在：$CLONE_PREFIX"
  else
    [[ -x "$SERVER_CONDA" ]] || die "找不到 Conda：$SERVER_CONDA"
    if [[ -e "$CLONE_PREFIX" ]]; then
      if [[ "$FORCE" == "1" ]]; then
        backup_existing "$CLONE_PREFIX"
      else
        die "环境目录已存在但不完整：$CLONE_PREFIX；检查后使用 --force"
      fi
    fi
    mkdir -p -- "$(dirname -- "$CLONE_PREFIX")"
    SOURCE_PREFIX="$(dirname -- "$(dirname -- "$SERVER_PYTHON")")"
    log "正在离线克隆 Conda 环境，可能需要数分钟：$SOURCE_PREFIX"
    CONDA_OFFLINE=true "$SERVER_CONDA" create \
      --yes \
      --offline \
      --prefix "$CLONE_PREFIX" \
      --clone "$SOURCE_PREFIX"
  fi
  RUNTIME_PYTHON="$CLONE_PREFIX/bin/python"
fi

ENV_FILE="$MODEL_DIR/.time_memory_env"
if ((!VERIFY_ONLY)); then
  mkdir -p -- "$MODEL_DIR"
  {
    printf '# 由 setup_time_memory_server.sh 生成；启动服务前可 source 本文件。\n'
    printf 'export TIME_MEMORY_PROJECT_ROOT=%q\n' "$PROJECT_DIR"
    printf 'export TIME_MEMORY_MODELS_ROOT=%q\n' "$MODEL_DIR"
    printf 'export TIME_MEMORY_LRASD_ROOT=%q\n' "$LRASD_DIR"
    printf 'export TIME_MEMORY_PYTHON=%q\n' "$RUNTIME_PYTHON"
    printf 'export HF_HUB_OFFLINE=1\n'
    printf 'export TRANSFORMERS_OFFLINE=1\n'
    printf 'export MODELSCOPE_OFFLINE=1\n'
    printf 'export PATH=%q:"$PATH"\n' "$(dirname -- "$RUNTIME_PYTHON")"
  } >"$ENV_FILE"
  chmod 0644 "$ENV_FILE"
  log "已生成运行环境文件：$ENV_FILE"
fi

log "开始检查 Python 库、CUDA、FFmpeg 和工程模块"
command -v ffmpeg >/dev/null 2>&1 || die "系统找不到 ffmpeg"
command -v ffprobe >/dev/null 2>&1 || die "系统找不到 ffprobe"

TIME_MEMORY_PROJECT_ROOT="$PROJECT_DIR" \
TIME_MEMORY_MODELS_ROOT="$MODEL_DIR" \
TIME_MEMORY_LRASD_ROOT="$LRASD_DIR" \
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
MODELSCOPE_OFFLINE=1 \
"$RUNTIME_PYTHON" - <<'PY'
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

project = Path(os.environ["TIME_MEMORY_PROJECT_ROOT"])
lrasd = Path(os.environ["TIME_MEMORY_LRASD_ROOT"])

required = [
    "torch",
    "torchaudio",
    "torchvision",
    "numpy",
    "funasr",
    "pyannote.audio",
    "cv2",
    "scipy",
    "sklearn",
    "pandas",
    "soundfile",
    "yaml",
    "python_speech_features",
    "scenedetect",
]

failed: list[str] = []
for name in required:
    try:
        __import__(name)
        print(f"[OK] Python import: {name}")
    except Exception as exc:
        failed.append(f"{name}: {type(exc).__name__}: {exc}")

try:
    import torch
    print(
        "[OK] PyTorch:",
        torch.__version__,
        "CUDA available:",
        torch.cuda.is_available(),
        "GPU count:",
        torch.cuda.device_count(),
    )
    if not torch.cuda.is_available():
        failed.append("torch.cuda.is_available() is False")
except Exception as exc:
    failed.append(f"torch CUDA check: {type(exc).__name__}: {exc}")

sys.path.insert(0, str(lrasd))
try:
    from model.faceDetector.s3fd import S3FD  # noqa: F401
    print("[OK] LR-ASD S3FD import")
except Exception as exc:
    failed.append(f"LR-ASD S3FD: {type(exc).__name__}: {exc}")

for filename in ("speaker_video_pipeline.py", "time_memory.py"):
    path = project / filename
    if not path.is_file():
        print(f"[SKIP] Project module not present yet: {filename}")
        continue
    if filename == "time_memory.py":
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
            print(f"[OK] Project syntax: {filename}")
        except Exception as exc:
            failed.append(f"{filename}: {type(exc).__name__}: {exc}")
        continue
    spec = importlib.util.spec_from_file_location(
        f"_time_memory_check_{path.stem}",
        path,
    )
    if spec is None or spec.loader is None:
        failed.append(f"cannot create import spec: {path}")
        continue
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        print(f"[OK] Project module: {filename}")
    except Exception as exc:
        failed.append(f"{filename}: {type(exc).__name__}: {exc}")

if failed:
    print("\nDependency verification failed:", file=sys.stderr)
    for item in failed:
        print(f"  - {item}", file=sys.stderr)
    raise SystemExit(1)
PY

cat <<EOF

准备完成。

Echo compute：${COMPUTE_DIR:-未自动识别}
工程目录：$PROJECT_DIR
模型目录：$MODEL_DIR
LR-ASD：$LRASD_DIR
运行 Python：$RUNTIME_PYTHON

服务启动前执行：
  source "$ENV_FILE"

服务进程必须使用上面的运行 Python，或使用包含相同依赖的环境启动。
EOF
