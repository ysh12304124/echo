from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RERANKER_", env_file=".env", extra="ignore"
    )

    model_path: str = "/home/realmagic/models/Qwen3-Reranker-0.6B"
    model_name: str = "Qwen3-Reranker-0.6B"
    internal_token: str = "echo-internal-dev-token"
    max_batch_size: int = 20
    max_length: int = 1024
    instruction: str = (
        "Given a question about the user's work memories, retrieve evidence passages "
        "that directly answer the question"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
