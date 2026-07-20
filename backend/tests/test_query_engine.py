from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.enums import (
    DataPartition,
    EvidenceType,
    MemoryStatus,
    QueryResultStatus,
    QueryScope,
    TimeScene,
)
from app.domain.models import Evidence, TimeMemory
from app.services.query_engine import QueryEngine, RetrievedEvidence


class StubRepository:
    def __init__(self, memory):
        self.memory = memory
        self.logs = []

    async def get_time_memory(self, _memory_id):
        return self.memory

    async def save_query_log(self, *args):
        self.logs.append(args)


class StubLLM:
    async def answer_query_structured(self, _question, _evidence_context):
        return {"answer": "下周三", "confidence": "high"}

    async def answer_query_multimodal(self, question, evidence_context, images):
        return await self.answer_query_structured(question, evidence_context)


class StubBlobStore:
    def get_url(self, key):
        return key

    async def get_path(self, key):
        return key


class RankedEvidenceQueryEngine(QueryEngine):
    def __init__(self, repo, providers, evidence):
        super().__init__(repo, providers)
        self.evidence = evidence

    async def _retrieve(self, _question, _scope, _memory_id, _space_id):
        return RetrievedEvidence(text=[self.evidence], visual=[])


@pytest.mark.asyncio
async def test_query_with_ranked_evidence_uses_configured_top_k():
    memory = TimeMemory(
        title="交付沟通",
        scene=TimeScene.MEETING,
        partition=DataPartition.WORK,
        status=MemoryStatus.COMPLETED,
    )
    evidence = Evidence(
        id=uuid4(),
        memory_id=memory.id,
        type=EvidenceType.TRANSCRIPT,
        content="张经理承诺下周三交付样品",
    )
    repo = StubRepository(memory)
    providers = SimpleNamespace(
        llm=lambda: StubLLM(),
        blob_store=lambda: StubBlobStore(),
    )
    engine = RankedEvidenceQueryEngine(repo, providers, evidence)

    result = await engine.query("什么时候交付？", QueryScope.GLOBAL_WORK)

    assert result.status == QueryResultStatus.CONFIRMED
    assert result.answer == "下周三"
    assert [item.evidence_id for item in result.evidences] == [evidence.id]
    assert len(repo.logs) == 1


@pytest.mark.asyncio
async def test_query_passes_visual_evidence_to_multimodal_llm(tmp_path):
    image_path = tmp_path / "frame.png"
    image_path.write_bytes(b"png")
    memory = TimeMemory(
        title="图像记忆",
        scene=TimeScene.MEETING,
        partition=DataPartition.WORK,
        status=MemoryStatus.COMPLETED,
    )
    evidence = Evidence(
        id=uuid4(),
        memory_id=memory.id,
        type=EvidenceType.VISUAL,
        content="红色测试图片",
        media_path=str(image_path),
    )
    repo = StubRepository(memory)

    class MultimodalStub(StubLLM):
        def __init__(self):
            self.images = []

        async def answer_query_multimodal(self, question, evidence_context, images):
            self.images = images
            return {"answer": "图片是红色", "confidence": "high"}

    llm = MultimodalStub()
    providers = SimpleNamespace(
        llm=lambda: llm,
        blob_store=lambda: StubBlobStore(),
    )
    engine = RankedEvidenceQueryEngine(repo, providers, evidence)

    async def retrieve_visual(*_args):
        return _visual_result(evidence)

    engine._retrieve = retrieve_visual

    result = await engine.query("图片是什么颜色？", QueryScope.GLOBAL_WORK)

    assert result.status == QueryResultStatus.CONFIRMED
    assert result.evidences[0].media_url == str(image_path)
    assert len(llm.images) == 1


def _visual_result(evidence):
    return RetrievedEvidence(text=[], visual=[evidence])
