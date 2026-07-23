from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLIP_DEMO_", env_file=".env", extra="ignore"
    )

    model_path: str = "/home/realmagic/models/chinese-clip-vit-base-patch16-fp16"
    image_root: str = "/home/realmagic/services/echo-clip-benchmark/images"
    default_quantization: str = "nf4"
    gpu_index: int = 0
    image_batch_size: int = 16
    top_k: int = 20
    text_max_length: int = 512

    @property
    def resolved_image_root(self) -> Path:
        return Path(self.image_root).expanduser().resolve()
