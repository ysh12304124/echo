from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class EmbeddingResult:
    vector: list[float]
    text: str


@dataclass
class RerankCandidate:
    id: str
    document: str


@dataclass
class RerankResult:
    id: str
    score: float


class RerankerUnavailable(RuntimeError):
    """The configured reranker cannot serve this query."""


class VectorIndexMismatch(RuntimeError):
    """The persisted vector index does not match the configured embedding model."""


class VisualEmbeddingUnavailable(RuntimeError):
    """The configured Chinese-CLIP service cannot serve an embedding request."""


@dataclass(frozen=True)
class VectorIndexInfo:
    model: str
    dimension: int
    count: int


@dataclass(frozen=True)
class ImageInput:
    path: str
    caption: str = ""


class LLMProvider(ABC):
    @abstractmethod
    async def summarize(self, context: str, prompt: str) -> str:
        pass

    @abstractmethod
    async def extract_events(self, transcript: str, scene: str) -> list[dict]:
        pass

    @abstractmethod
    async def answer_query(self, question: str, evidence_context: str) -> str:
        pass

    async def extract_entities(self, transcript: str, scene: str) -> list[dict]:
        """抽取人物/项目/设备等实体。返回 [{"name","type","confidence"}]。默认空。"""
        return []

    async def answer_query_structured(
        self, question: str, evidence_context: str
    ) -> dict:
        """证据接地问答，返回 {"answer": str, "confidence": "high|medium|low"}。

        默认基于 answer_query 包装，便于旧实现无缝兼容。
        """
        answer = await self.answer_query(question, evidence_context)
        return {"answer": answer, "confidence": "high" if answer else "low"}

    async def answer_query_multimodal(
        self,
        question: str,
        evidence_context: str,
        images: list[ImageInput],
    ) -> dict:
        """Return answer, confidence, and the evidence refs actually used."""
        return await self.answer_query_structured(question, evidence_context)

    async def build_navigation_summary(self, scene: str, transcript: str) -> dict:
        """生成导航型摘要，返回 {"persons","topics","key_moments","suggested_questions"}。默认空。"""
        return {}


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> EmbeddingResult:
        pass

    async def embed_query(self, text: str) -> EmbeddingResult:
        """Embed a retrieval query. Providers may apply model-specific task prefixes."""
        return await self.embed(text)

    async def embed_document(self, text: str) -> EmbeddingResult:
        """Embed an indexed document. Providers may apply model-specific task prefixes."""
        return await self.embed(text)


class VisualEmbeddingProvider(ABC):
    @abstractmethod
    async def embed_text(self, text: str) -> EmbeddingResult:
        pass

    @abstractmethod
    async def embed_images(self, images: list[bytes]) -> list[EmbeddingResult]:
        pass


class RerankerProvider(ABC):
    @abstractmethod
    async def rerank(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[RerankResult]:
        pass


class VectorStore(ABC):
    @abstractmethod
    async def upsert(self, id: str, vector: list[float], metadata: dict) -> None:
        pass

    @abstractmethod
    async def search(
        self, vector: list[float], top_k: int = 10, filter: Optional[dict] = None
    ) -> list[tuple[str, float, dict]]:
        pass

    async def fts_search(
        self, query: str, top_k: int = 10, filter: Optional[dict] = None
    ) -> list[tuple[str, float, dict]]:
        """Return BM25/FTS scores when the store has a full-text index."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, id: str) -> None:
        pass

    @abstractmethod
    async def replace_all(
        self, entries: list[tuple[str, list[float], dict]]
    ) -> None:
        """Atomically replace the complete vector collection."""
        pass

    @abstractmethod
    async def index_info(self) -> Optional[VectorIndexInfo]:
        """Return and validate the persisted embedding index identity."""
        pass

    async def delete_by_filter(self, filter: dict) -> None:
        """按 metadata 过滤批量删除，用于记忆/空间删除时的级联清理。"""
        raise NotImplementedError


class BlobStore(ABC):
    @abstractmethod
    async def save(self, key: str, data: bytes, content_type: str) -> str:
        pass

    @abstractmethod
    async def append(self, key: str, data: bytes) -> str:
        """按顺序把新分片追加写入 key 对应的文件，用于视频边录边传的不落地转发。"""
        pass

    @abstractmethod
    async def patch(self, key: str, offset: int, data: bytes) -> str:
        """覆盖写 key 对应文件从 offset 开始的字节，不改变文件长度以外的内容。

        用于修正视频边录边发时已发出的头部信息（如 MediaRecorder 在 stop() 时
        回改的 mdat box 64bit size 字段），须在 append 触发的最终 rename 之前调用。
        """
        pass

    @abstractmethod
    async def get_path(self, key: str) -> Optional[str]:
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        pass

    @abstractmethod
    def get_url(self, key: str) -> str:
        pass
