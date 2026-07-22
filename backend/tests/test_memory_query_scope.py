from types import SimpleNamespace

import pytest

from app.domain.enums import (
    ConfidenceLevel,
    DataPartition,
    EvidenceType,
    MemoryStatus,
    QueryResultStatus,
    QueryScope,
    TimeScene,
)
from app.domain.models import Evidence, TimeMemory
from app.services.query_engine import QueryEngine


class MemoryScopeRepository:
    def __init__(self, memory: TimeMemory, evidence: Evidence):
        self.memory = memory
        self.evidence = evidence
        self.logs = []

    async def get_time_memory(self, memory_id):
        return self.memory if memory_id == self.memory.id else None

    async def list_evidences(self, memory_id):
        return [self.evidence] if memory_id == self.memory.id else []

    async def save_query_log(self, *args):
        self.logs.append(args)


class MemoryScopeBlobStore:
    def __init__(self, image_path):
        self.image_path = image_path

    async def get_path(self, key):
        return self.image_path if key == "frames/starriver.png" else None

    def get_url(self, key):
        return f"/api/v1/media/{key}"


class MemoryScopeLLM:
    def __init__(self):
        self.context = ""
        self.images = []

    async def answer_query_multimodal(self, question, evidence_context, images):
        self.context = evidence_context
        self.images = images
        return {
            "answer": "谷岩负责版本推进。",
            "confidence": "high",
            "evidence_sufficient": True,
            "used_evidence_refs": ["文本1", "图片1"],
        }


@pytest.mark.asyncio
async def test_memory_scope_sends_its_transcript_and_keyframes_directly_to_vlm(
    tmp_path,
):
    image_path = tmp_path / "starriver.png"
    image_path.write_bytes(b"png")
    memory = TimeMemory(
        title="星河 v2.6 发布流程评审",
        scene=TimeScene.MEETING,
        partition=DataPartition.WORK,
        status=MemoryStatus.COMPLETED,
        key_frames=[
            {
                "media_path": "frames/starriver.png",
                "description": "星河 v2.6 蓝色四节点流程白板",
                "timestamp_ms": 79_000,
                "confidence": "high",
            }
        ],
    )
    transcript = Evidence(
        memory_id=memory.id,
        type=EvidenceType.TRANSCRIPT,
        content="星河 v2.6 由谷岩负责版本推进，发布时间暂定为6月30日晚九点。",
        confidence=ConfidenceLevel.HIGH,
    )
    repo = MemoryScopeRepository(memory, transcript)
    llm = MemoryScopeLLM()
    providers = SimpleNamespace(
        settings=SimpleNamespace(
            reranker_top_k=5,
            visual_retrieval_top_k=3,
        ),
        llm=lambda: llm,
        blob_store=lambda: MemoryScopeBlobStore(image_path),
    )

    result = await QueryEngine(repo, providers).query(
        "该项目负责人是谁？",
        QueryScope.MEMORY,
        memory_id=memory.id,
    )

    assert result.status == QueryResultStatus.CONFIRMED
    assert result.answer == "谷岩负责版本推进。"
    assert [item.type for item in result.evidences] == [
        EvidenceType.TRANSCRIPT,
        EvidenceType.VISUAL,
    ]
    assert all(item.used_in_answer for item in result.evidences)
    assert "谷岩负责版本推进" in llm.context
    assert "星河 v2.6 蓝色四节点流程白板" in llm.context
    assert [image.path for image in llm.images] == [image_path]
    assert len(repo.logs) == 1
