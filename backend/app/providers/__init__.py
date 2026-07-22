from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.providers.base import (
    BlobStore,
    EmbeddingProvider,
    LLMProvider,
    RerankerProvider,
    VectorStore,
)
from app.providers.mock.providers import (
    InMemoryVectorStore,
    LocalBlobStore,
    MockEmbeddingProvider,
    MockLLMProvider,
    MockRerankerProvider,
    MockVisualEmbeddingProvider,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ECHO_", env_file=".env", extra="ignore")

    blob_storage_path: str = "./data/blobs"
    provider_mode: str = "mock"  # mock | local
    database_url: str = "sqlite+aiosqlite:///./data/echo.db"
    lance_db_path: str = "./data/lancedb"

    # 本地 OpenAI 兼容服务配置（provider_mode=local 时生效）
    llm_base_url: str = "http://localhost:8001/v1"
    llm_model: str = "qwen2.5"
    llm_api_key: str = "not-needed"

    embedding_base_url: str = "http://192.168.0.100:11434/v1"
    embedding_model: str = "qwen3-embedding:0.6b-q4_k_m"
    embedding_dimension: int = 1024
    embedding_api_key: str = "not-needed"
    embedding_query_instruction: str = (
        "Given a question about the user's work memories, retrieve evidence passages "
        "that directly answer the question"
    )

    visual_embedding_base_url: str = "http://192.168.0.100:8300"
    visual_embedding_model: str = "chinese-clip-vit-base-patch16"
    visual_embedding_dimension: int = 512
    visual_embedding_api_key: str = "echo-internal-dev-token"
    visual_embedding_timeout_seconds: float = 30.0
    visual_retrieval_enabled: bool = True
    visual_retrieval_candidates: int = 10
    visual_retrieval_top_k: int = 3
    visual_retrieval_min_score: float = 0.37
    visual_retrieval_medium_score: float = 0.40
    visual_retrieval_high_score: float = 0.45
    visual_max_image_bytes: int = 10 * 1024 * 1024

    # 算力服务（compute/，独立进程，同机 localhost 通信）。
    # compute_provider_mode 独立于 provider_mode：默认 mock，即使 provider_mode=local 也不会
    # 在测试/离线环境里真的发网络请求；只有显式设为 http 才会真的提交给 compute_base_url。
    compute_provider_mode: str = "mock"  # mock | http
    compute_base_url: str = "http://127.0.0.1:8100"
    request_timeout_seconds: float = 120.0
    # 算力服务回调后台时使用的地址；后台自己生成 callback_url 时用这个拼接。
    public_callback_base_url: str = "http://127.0.0.1:8000"
    # 后台 /internal/* 回调路由与算力服务提交请求之间约定的共享密钥，仅做简单头校验。
    internal_token: str = "echo-internal-dev-token"

    reranker_enabled: bool = True
    reranker_base_url: str = "http://192.168.0.100:8200"
    reranker_model: str = "Qwen3-Reranker-0.6B"
    reranker_candidates: int = 20
    reranker_top_k: int = 5
    reranker_min_score: float = 0.5
    reranker_medium_score: float = 0.65
    reranker_high_score: float = 0.8
    reranker_timeout_seconds: float = 10.0
    voice_query_max_seconds: int = 60
    voice_query_min_seconds: float = 0.5
    asr_min_avg_logprob: float = -1.0
    hybrid_retrieval_enabled: bool = True
    hybrid_vector_weight: float = 0.65
    hybrid_bm25_weight: float = 0.35
    bm25_k1: float = 1.2
    bm25_b: float = 0.75


@lru_cache
def get_settings() -> Settings:
    return Settings()


class ProviderFactory:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._vector_store: Optional[VectorStore] = None
        self._visual_vector_store: Optional[VectorStore] = None
        self._is_local = self.settings.provider_mode.lower() == "local"

    def _client(self, base_url: str, api_key: str):
        from app.providers.local.openai_client import OpenAICompatClient

        return OpenAICompatClient(base_url=base_url, api_key=api_key)

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
                self._client(s.embedding_base_url, s.embedding_api_key),
                s.embedding_model,
                s.embedding_query_instruction,
                s.embedding_dimension,
            )
        return MockEmbeddingProvider()

    def vector_store(self) -> VectorStore:
        if self._vector_store is None:
            if self._is_local:
                from app.providers.lance_vector import LanceDBVectorStore

                self._vector_store = LanceDBVectorStore(
                    self.settings.lance_db_path,
                    self.settings.embedding_model,
                    self.settings.embedding_dimension,
                    namespace="text",
                    enable_fts=True,
                )
            else:
                self._vector_store = InMemoryVectorStore()
        return self._vector_store

    def visual_embedding(self):
        if not self._is_local:
            return MockVisualEmbeddingProvider()
        from app.providers.local.visual import HttpVisualEmbeddingProvider

        s = self.settings
        return HttpVisualEmbeddingProvider(
            base_url=s.visual_embedding_base_url,
            model=s.visual_embedding_model,
            api_key=s.visual_embedding_api_key,
            dimension=s.visual_embedding_dimension,
            timeout=s.visual_embedding_timeout_seconds,
        )

    def visual_vector_store(self) -> VectorStore:
        if self._visual_vector_store is None:
            if self._is_local:
                s = self.settings
                from app.providers.lance_vector import LanceDBVectorStore

                self._visual_vector_store = LanceDBVectorStore(
                    s.lance_db_path,
                    s.visual_embedding_model,
                    s.visual_embedding_dimension,
                    namespace="visual",
                )
            else:
                self._visual_vector_store = InMemoryVectorStore()
        return self._visual_vector_store

    def reranker(self) -> RerankerProvider:
        if not self._is_local:
            return MockRerankerProvider()
        if not self.settings.reranker_enabled:
            return MockRerankerProvider()
        from app.providers.local.reranker import HttpRerankerProvider

        s = self.settings
        return HttpRerankerProvider(
            base_url=s.reranker_base_url,
            model=s.reranker_model,
            api_key=s.internal_token,
            timeout=s.reranker_timeout_seconds,
        )

    def blob_store(self) -> BlobStore:
        return LocalBlobStore(self.settings.blob_storage_path)


_provider_factory: Optional[ProviderFactory] = None


def get_provider_factory() -> ProviderFactory:
    global _provider_factory
    if _provider_factory is None:
        _provider_factory = ProviderFactory()
    return _provider_factory
