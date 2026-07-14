from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.providers.base import (
    ASRProvider,
    BlobStore,
    EmbeddingProvider,
    LLMProvider,
    OCRProvider,
    ReconstructionProvider,
    VectorStore,
    VisionProvider,
)
from app.providers.mock.providers import (
    InMemoryVectorStore,
    LocalBlobStore,
    MockASRProvider,
    MockEmbeddingProvider,
    MockLLMProvider,
    MockOCRProvider,
    MockReconstructionProvider,
    MockVisionProvider,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ECHO_", env_file=".env", extra="ignore")

    blob_storage_path: str = "./data/blobs"
    provider_mode: str = "mock"  # mock | local
    database_url: str = "sqlite+aiosqlite:///./data/echo.db"
    vector_db_path: str = "./data/vectors.db"

    # 本地 OpenAI 兼容服务配置（provider_mode=local 时生效）
    llm_base_url: str = "http://localhost:8001/v1"
    llm_model: str = "qwen2.5"
    llm_api_key: str = "not-needed"

    vlm_base_url: str = "http://localhost:8002/v1"
    vlm_model: str = "qwen2.5-vl"
    vlm_api_key: str = "not-needed"

    asr_base_url: str = "http://localhost:8003/v1"
    asr_model: str = "whisper-1"
    asr_api_key: str = "not-needed"
    asr_language: Optional[str] = "zh"

    embedding_base_url: str = "http://localhost:8004/v1"
    embedding_model: str = "bge-m3"
    embedding_api_key: str = "not-needed"

    # 3D 重建服务（可选，未配置则用 mock 关键帧分析）
    reconstruction_base_url: Optional[str] = None

    fastgs_ssh_host: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FASTGS_SSH_HOST", "ECHO_FASTGS_SSH_HOST"),
    )
    fastgs_ssh_port: int = Field(
        default=22,
        validation_alias=AliasChoices("FASTGS_SSH_PORT", "ECHO_FASTGS_SSH_PORT"),
    )
    fastgs_ssh_user: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FASTGS_SSH_USER", "ECHO_FASTGS_SSH_USER"),
    )
    fastgs_ssh_password: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("FASTGS_SSH_PASSWORD", "ECHO_FASTGS_SSH_PASSWORD"),
    )
    fastgs_remote_project: str = Field(
        default="/home/liangjiahua/FastGS",
        validation_alias=AliasChoices("FASTGS_REMOTE_PROJECT", "ECHO_FASTGS_REMOTE_PROJECT"),
    )
    fastgs_remote_env: str = Field(
        default="fastgs",
        validation_alias=AliasChoices("FASTGS_REMOTE_ENV", "ECHO_FASTGS_REMOTE_ENV"),
    )
    fastgs_remote_work_root: str = Field(
        default="/tmp/echo-fastgs",
        validation_alias=AliasChoices("FASTGS_REMOTE_WORK_ROOT", "ECHO_FASTGS_REMOTE_WORK_ROOT"),
    )
    fastgs_train_iterations: int = Field(
        default=30000,
        validation_alias=AliasChoices("FASTGS_TRAIN_ITERATIONS", "ECHO_FASTGS_TRAIN_ITERATIONS"),
    )
    fastgs_train_timeout_seconds: int = Field(
        default=1800,
        validation_alias=AliasChoices("FASTGS_TRAIN_TIMEOUT_SECONDS", "ECHO_FASTGS_TRAIN_TIMEOUT_SECONDS"),
    )
    fastgs_python_executable: str = Field(
        default="/home/liangjiahua/miniconda3/envs/fastgs/bin/python",
        validation_alias=AliasChoices("FASTGS_PYTHON_EXECUTABLE", "ECHO_FASTGS_PYTHON_EXECUTABLE"),
    )
    fastgs_conda_executable: str = Field(
        default="/home/liangjiahua/miniconda3/bin/conda",
        validation_alias=AliasChoices("FASTGS_CONDA_EXECUTABLE", "ECHO_FASTGS_CONDA_EXECUTABLE"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


class ProviderFactory:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._vector_store: Optional[VectorStore] = None
        self._is_local = self.settings.provider_mode.lower() == "local"

    def _client(self, base_url: str, api_key: str):
        from app.providers.local.openai_client import OpenAICompatClient

        return OpenAICompatClient(base_url=base_url, api_key=api_key)

    def asr(self) -> ASRProvider:
        if self._is_local:
            from app.providers.local.providers import WhisperASRProvider

            s = self.settings
            return WhisperASRProvider(
                self._client(s.asr_base_url, s.asr_api_key), s.asr_model, s.asr_language
            )
        return MockASRProvider()

    def vision(self) -> VisionProvider:
        if self._is_local:
            return self._vlm()
        return MockVisionProvider()

    def ocr(self) -> OCRProvider:
        if self._is_local:
            return self._vlm()
        return MockOCRProvider()

    def _vlm(self):
        from app.providers.local.providers import LocalVLMProvider

        s = self.settings
        return LocalVLMProvider(self._client(s.vlm_base_url, s.vlm_api_key), s.vlm_model)

    def llm(self) -> LLMProvider:
        if self._is_local:
            from app.providers.local.providers import LocalLLMProvider

            s = self.settings
            return LocalLLMProvider(
                self._client(s.llm_base_url, s.llm_api_key), s.llm_model
            )
        return MockLLMProvider()

    def embedding(self) -> EmbeddingProvider:
        if self._is_local:
            from app.providers.local.providers import LocalEmbeddingProvider

            s = self.settings
            return LocalEmbeddingProvider(
                self._client(s.embedding_base_url, s.embedding_api_key), s.embedding_model
            )
        return MockEmbeddingProvider()

    def vector_store(self) -> VectorStore:
        if self._vector_store is None:
            if self._is_local:
                from app.providers.sqlite_vector import SqliteVectorStore

                self._vector_store = SqliteVectorStore(self.settings.vector_db_path)
            else:
                self._vector_store = InMemoryVectorStore()
        return self._vector_store

    def blob_store(self) -> BlobStore:
        return LocalBlobStore(self.settings.blob_storage_path)

    def reconstruction(self) -> ReconstructionProvider:
        return MockReconstructionProvider()


_provider_factory: Optional[ProviderFactory] = None


def get_provider_factory() -> ProviderFactory:
    global _provider_factory
    if _provider_factory is None:
        _provider_factory = ProviderFactory()
    return _provider_factory
