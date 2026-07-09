from pathlib import Path
from typing import Optional
from uuid import uuid4

import numpy as np

from app.providers.base import (
    ASRProvider,
    BlobStore,
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    OCRProvider,
    OCRResult,
    ReconstructionProvider,
    ReconstructionResult,
    TranscriptSegment,
    VectorStore,
    VisionProvider,
    VisionResult,
)


class MockASRProvider(ASRProvider):
  async def transcribe(self, audio_path: str) -> list[TranscriptSegment]:
    return [
      TranscriptSegment(
        text="张经理说周五前交方案",
        start_ms=0,
        end_ms=5000,
        speaker_id="speaker_a",
        confidence=0.92,
      ),
      TranscriptSegment(
        text="白板上写了Q3经营目标",
        start_ms=5000,
        end_ms=10000,
        speaker_id="speaker_b",
        confidence=0.88,
      ),
      TranscriptSegment(
        text="客户提到良率需要提升到98%",
        start_ms=10000,
        end_ms=15000,
        speaker_id="speaker_c",
        confidence=0.85,
      ),
    ]


class MockVisionProvider(VisionProvider):
  async def analyze_frame(self, image_path: str) -> VisionResult:
    name = Path(image_path).stem
    if "whiteboard" in name.lower():
      return VisionResult(summary="白板画面，包含Q3经营目标", labels=["whiteboard", "meeting"])
    if "device" in name.lower() or "smt" in name.lower():
      return VisionResult(summary="SMT车间设备画面", labels=["device", "factory"])
    return VisionResult(summary="会议现场画面", labels=["meeting", "general"])

  async def should_keep_frame(self, image_path: str) -> bool:
    if "blur" in image_path.lower() or "duplicate" in image_path.lower():
      return False
    return True

  async def summarize_session(self, transcript: str, image_path: Optional[str]) -> dict:
    return {
      "person_count": 2,
      "space": "会议室",
      "voice_summary": (transcript[:120] if transcript else "本段记忆无语音内容"),
    }


class MockOCRProvider(OCRProvider):
  async def extract_text(self, image_path: str) -> OCRResult:
    name = str(image_path).lower()
    if "whiteboard" in name:
      return OCRResult(text="Q3经营目标：营收增长20%", confidence=0.9)
    if "device" in name or "smt" in name:
      return OCRResult(text="贴片机 SM-880", confidence=0.88)
    return OCRResult(text="", confidence=0.0)


class MockLLMProvider(LLMProvider):
  async def summarize(self, context: str, prompt: str) -> str:
    if "quality" in context.lower() or "孩子" in context:
      return "家庭时光记录"
    if "onsite" in context.lower() or "车间" in context:
      return "苏州工厂拜访"
    if "meeting" in context.lower() or "会议" in context:
      return "Q3经营会"
    return "时间记忆记录"

  async def extract_events(self, transcript: str, scene: str) -> list[dict]:
    events = []
    if "承诺" in transcript or "交方案" in transcript or "周五" in transcript:
      events.append({
        "type": "commitment",
        "label": "承诺交付方案",
        "start_ms": 0,
        "confidence": "high",
      })
    if "白板" in transcript or "经营目标" in transcript:
      events.append({
        "type": "whiteboard_change",
        "label": "白板内容变化",
        "start_ms": 5000,
        "confidence": "high",
      })
    if "良率" in transcript or "设备" in transcript:
      events.append({
        "type": "device_appear",
        "label": "设备/业务讨论",
        "start_ms": 10000,
        "confidence": "high",
      })
    if "展示" in transcript or "作品" in transcript:
      events.append({
        "type": "work_showcase",
        "label": "作品展示",
        "start_ms": 0,
        "confidence": "high",
      })
    return events

  async def answer_query(self, question: str, evidence_context: str) -> str:
    q = question.lower()
    if "承诺" in question or "交方案" in question:
      if "张经理" in evidence_context and "周五" in evidence_context:
        return "张经理承诺周五前交方案"
      if "周五" in evidence_context and "张经理" not in evidence_context:
        return ""
    if "白板" in question:
      if "经营目标" in evidence_context or "Q3" in evidence_context:
        return "白板上写了Q3经营目标：营收增长20%"
    if "设备" in question or "车间" in question:
      if "贴片机" in evidence_context or "SMT" in evidence_context:
        return "SMT车间有贴片机 SM-880 等设备"
    if "展示" in question:
      if "作品" in evidence_context or "展示" in evidence_context:
        return "记录了作品展示相关内容"
    if "答应" in question:
      if "承诺" in evidence_context:
        return "有相关承诺记录"
    return ""


class MockEmbeddingProvider(EmbeddingProvider):
  DIM = 256

  async def embed(self, text: str) -> EmbeddingResult:
    # 词法哈希嵌入：相似文本 → 相似向量，使检索排序对测试可确定且语义相关。
    vec = np.zeros(self.DIM, dtype=np.float32)
    tokens = list(text)
    tokens += [text[i : i + 2] for i in range(len(text) - 1)]
    for tok in tokens:
      idx = (hash(tok) % self.DIM + self.DIM) % self.DIM
      vec[idx] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
      vec = vec / norm
    return EmbeddingResult(vector=vec.tolist(), text=text)


class InMemoryVectorStore(VectorStore):
  def __init__(self):
    self._store: dict[str, tuple[list[float], dict]] = {}

  async def upsert(self, id: str, vector: list[float], metadata: dict) -> None:
    self._store[id] = (vector, metadata)

  async def search(
    self, vector: list[float], top_k: int = 10, filter: Optional[dict] = None
  ) -> list[tuple[str, float, dict]]:
    results = []
    q = np.array(vector)
    for id, (v, meta) in self._store.items():
      if filter:
        match = all(meta.get(k) == val for k, val in filter.items())
        if not match:
          continue
      score = float(np.dot(q, np.array(v)) / (np.linalg.norm(q) * np.linalg.norm(v) + 1e-8))
      results.append((id, score, meta))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]

  async def delete(self, id: str) -> None:
    self._store.pop(id, None)

  async def delete_by_filter(self, filter: dict) -> None:
    to_delete = [
      id
      for id, (_, meta) in self._store.items()
      if all(meta.get(k) == v for k, v in filter.items())
    ]
    for id in to_delete:
      self._store.pop(id, None)


class LocalBlobStore(BlobStore):
  def __init__(self, base_path: str):
    self.base_path = Path(base_path)
    self.base_path.mkdir(parents=True, exist_ok=True)

  async def save(self, key: str, data: bytes, content_type: str) -> str:
    path = self.base_path / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)

  async def get_path(self, key: str) -> Optional[str]:
    path = self.base_path / key
    return str(path) if path.exists() else None

  async def delete(self, key: str) -> None:
    path = self.base_path / key
    if path.exists():
      path.unlink()

  def get_url(self, key: str) -> str:
    return f"/api/v1/media/{key}"


class MockReconstructionProvider(ReconstructionProvider):
  async def reconstruct(self, frame_paths: list[str]) -> ReconstructionResult:
    quality = "excellent" if len(frame_paths) >= 10 else "good"
    if len(frame_paths) < 3:
      quality = "retry_required"
    return ReconstructionResult(
      model_url="/api/v1/media/placeholder_3d.glb",
      quality=quality,
      anchor_suggestions=[
        {"name": "入口", "type": "door", "position": {"x": 0, "y": 0, "z": 0}},
        {"name": "设备区", "type": "device", "position": {"x": 2, "y": 0, "z": 1}},
      ],
    )