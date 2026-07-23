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
    shared_blob_root: str = "../backend/data/blobs"
    max_voice_query_seconds: int = 60


@lru_cache
def get_settings() -> ComputeSettings:
    return ComputeSettings()
