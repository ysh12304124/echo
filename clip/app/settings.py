from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLIP_", env_file=".env", extra="ignore"
    )

    model_path: str = (
        "/home/realmagic/models/chinese-clip-vit-base-patch16-fp16"
    )
    model_name: str = "chinese-clip-vit-base-patch16"
    internal_token: str = "echo-internal-dev-token"
    max_batch_size: int = 16
    max_image_bytes: int = 10 * 1024 * 1024
    embedding_dimension: int = 512
    text_max_length: int = 512


@lru_cache
def get_settings() -> Settings:
    return Settings()
