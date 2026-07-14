from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class TranscriptSegment:
    text: str
    start_ms: int
    end_ms: int
    speaker_id: Optional[str] = None
    confidence: float = 1.0


@dataclass
class VisionResult:
    summary: str
    is_informative: bool = True
    labels: list[str] = None

    def __post_init__(self):
        if self.labels is None:
            self.labels = []


@dataclass
class OCRResult:
    text: str
    confidence: float = 1.0


@dataclass
class EmbeddingResult:
    vector: list[float]
    text: str


@dataclass
class ReconstructionResult:
    model_url: str
    quality: str
    anchor_suggestions: list[dict]


class ASRProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: str) -> list[TranscriptSegment]:
        pass


class VisionProvider(ABC):
    @abstractmethod
    async def analyze_frame(self, image_path: str) -> VisionResult:
        pass

    @abstractmethod
    async def should_keep_frame(self, image_path: str) -> bool:
        """初筛：模糊/重复/无信息帧丢弃"""
        pass

    async def summarize_session(
        self, transcript: str, image_path: Optional[str]
    ) -> dict:
        """依据全量语音转写 + 首帧图片，产出一段记忆的结构化摘要。

        返回 {"person_count": int, "space": str, "voice_summary": str}。默认空。
        """
        return {}

    async def describe_scene(self, image_path: str) -> str:
        """用 VLM 分析单张图片，返回一句话场景描述。默认空。"""
        return ""


class OCRProvider(ABC):
    @abstractmethod
    async def extract_text(self, image_path: str) -> OCRResult:
        pass


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

    async def build_navigation_summary(self, scene: str, transcript: str) -> dict:
        """生成导航型摘要，返回 {"persons","topics","key_moments","suggested_questions"}。默认空。"""
        return {}


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> EmbeddingResult:
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

    @abstractmethod
    async def delete(self, id: str) -> None:
        pass

    async def delete_by_filter(self, filter: dict) -> None:
        """按 metadata 过滤批量删除，用于记忆/空间删除时的级联清理。"""
        raise NotImplementedError


class BlobStore(ABC):
    @abstractmethod
    async def save(self, key: str, data: bytes, content_type: str) -> str:
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


class ReconstructionProvider(ABC):
    @abstractmethod
    async def reconstruct(self, frame_paths: list[str]) -> ReconstructionResult:
        pass
