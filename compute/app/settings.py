"""算力服务配置。与 backend/app/providers Settings 相互独立，各自读各自的 .env。"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class ComputeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COMPUTE_", env_file=".env", extra="ignore")

    port: int = 8100
    # 需与 backend 的 ECHO_INTERNAL_TOKEN 保持一致，用于回调时的简单头校验。
    internal_token: str = "echo-internal-dev-token"
    # 提交/回调网络请求的超时时间。
    request_timeout_seconds: float = 120.0

    # Whisper(OpenAI 兼容 /v1/audio/transcriptions)，供 analyze/audio.py 使用。
    # 默认指向 compute/models/asr-whisper/start.sh 起的本机服务(默认端口 8081)。
    asr_base_url: str = "http://127.0.0.1:8081/v1"
    asr_model: str = "whisper-1"
    asr_api_key: str = "not-needed"
    asr_language: Optional[str] = "zh"

    # ---- 空间记忆(FastGS 3DGS) 相关配置 ----
    # FastGS 项目本地路径（含 train.py / convert.py / scripts/reconstruct_images.py）。
    # 相对 compute 服务的 cwd 解析，也可以填绝对路径。
    fastgs_dir: str = "fastgs"
    # 跑 FastGS 用的 Python 解释器（需装好 torch + FastGS 3 个 CUDA 子模块）。
    # Echo 项目专用 conda 环境，与其他项目隔离。
    fastgs_python: str = "/home/asus/miniconda3/envs/echo/bin/python"
    # FastGS 的 conda 环境名（reconstruct_images.py 内部 conda run 用）。
    fastgs_conda_env: str = "echo"
    # conda 二进制路径。
    fastgs_conda_executable: str = "/home/asus/miniconda3/bin/conda"
    # COLMAP 二进制路径（apt 装的默认在 /usr/bin/colmap）。
    fastgs_colmap_executable: str = "/usr/bin/colmap"
    # FastGS 训练迭代次数（3000 快速验证，30000 高质量）。
    fastgs_train_iterations: int = 3000
    # 视频抽帧帧率（fps）。经验：15fps 对普通手持视频足够 COLMAP 特征匹配。
    fastgs_extract_fps: int = 15
    # FastGS 单次任务的最大用时（秒）。
    fastgs_timeout_seconds: int = 2400
    # COLMAP 是否用 GPU（apt colmap 常无 CUDA，默认关闭）。
    fastgs_colmap_use_gpu: bool = False
    # 特征提取的最大特征数上限（FastGS 默认 8192）。
    fastgs_max_num_features: int = 8192
    # 工作根目录，每个 job 用 <root>/<job_id>/ 作为独立工作区。
    fastgs_work_root: str = "/tmp/echo-fastgs"

    # Blob 共享盘路径（与 backend 的 ECHO_BLOB_STORAGE_PATH 相同）。
    # compute 把 PLY/poses/anchor 写到这里，backend /api/v1/media 会自动服务。
    blob_storage_path: str = "../backend/data/blobs"


@lru_cache
def get_settings() -> ComputeSettings:
    return ComputeSettings()
