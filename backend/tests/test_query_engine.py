from types import SimpleNamespace
from uuid import uuid4

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
from app.services.query_engine import (
    QueryEngine,
    RetrievedEvidence,
    retrieval_confidence,
)


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
        return {
            "answer": "下周三",
            "confidence": "high",
            "used_evidence_refs": ["文本1"],
        }

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
async def test_query_rejects_answer_when_model_marks_evidence_insufficient():
    memory = TimeMemory(
        title="东泵房巡检",
        scene=TimeScene.ONSITE,
        partition=DataPartition.WORK,
        status=MemoryStatus.COMPLETED,
    )
    evidence = Evidence(
        id=uuid4(),
        memory_id=memory.id,
        type=EvidenceType.TRANSCRIPT,
        content="东泵房黄色手轮阀由高师傅复检",
    )
    repo = StubRepository(memory)

    class InsufficientLLM(StubLLM):
        async def answer_query_multimodal(self, question, evidence_context, images):
            return {
                "answer": "高师傅负责复检",
                "confidence": "medium",
                "evidence_sufficient": False,
                "used_evidence_refs": ["文本1"],
            }

    providers = SimpleNamespace(
        llm=lambda: InsufficientLLM(),
        blob_store=lambda: StubBlobStore(),
    )
    engine = RankedEvidenceQueryEngine(repo, providers, evidence)

    result = await engine.query("南泵房红色蝶阀由谁复检？", QueryScope.GLOBAL_WORK)

    assert result.status == QueryResultStatus.NOT_FOUND
    assert result.answer is None
    assert result.uncertainty_reason == "检索证据不足，无法回答"
    assert result.evidences[0].used_in_answer is False


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
            return {
                "answer": "图片1是红色",
                "confidence": "high",
                "used_evidence_refs": ["图片1"],
            }

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
    assert result.evidences[0].used_in_answer is True
    assert len(llm.images) == 1
    assert llm.images[0].caption.startswith("图片1: 红色测试图片;")


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.39, ConfidenceLevel.LOW),
        (0.40, ConfidenceLevel.MEDIUM),
        (0.449, ConfidenceLevel.MEDIUM),
        (0.45, ConfidenceLevel.HIGH),
    ],
)
def test_retrieval_confidence_uses_model_score(score, expected):
    assert retrieval_confidence(score, 0.40, 0.45) == expected


@pytest.mark.asyncio
async def test_query_keeps_unselected_low_relevance_visual_for_debugging(tmp_path):
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"png")
    memory = TimeMemory(
        title="候选图片",
        scene=TimeScene.MEETING,
        partition=DataPartition.WORK,
        status=MemoryStatus.COMPLETED,
    )
    evidence = Evidence(
        id=uuid4(),
        memory_id=memory.id,
        type=EvidenceType.VISUAL,
        content="低相关候选",
        media_path=str(image_path),
        confidence=ConfidenceLevel.LOW,
        metadata={"source_confidence": "high", "similarity_score": 0.381},
    )
    repo = StubRepository(memory)

    class RefusingLLM(StubLLM):
        async def answer_query_multimodal(self, question, evidence_context, images):
            return {
                "answer": "",
                "confidence": "low",
                "used_evidence_refs": [],
            }

    providers = SimpleNamespace(
        llm=lambda: RefusingLLM(),
        blob_store=lambda: StubBlobStore(),
    )
    engine = RankedEvidenceQueryEngine(repo, providers, evidence)

    async def retrieve_visual(*_args):
        return _visual_result(evidence)

    engine._retrieve = retrieve_visual

    result = await engine.query("不相关的问题", QueryScope.GLOBAL_WORK)

    assert result.status == QueryResultStatus.NOT_FOUND
    assert result.uncertainty_reason == "检索证据不足，无法回答"
    assert len(result.evidences) == 1
    assert result.evidences[0].confidence == ConfidenceLevel.LOW
    assert result.evidences[0].source_confidence == ConfidenceLevel.HIGH
    assert result.evidences[0].retrieval_score == pytest.approx(0.381)
    assert result.evidences[0].used_in_answer is False


@pytest.mark.asyncio
async def test_query_rejects_answer_with_unbound_image_reference(tmp_path):
    image_path = tmp_path / "candidate.png"
    image_path.write_bytes(b"png")
    memory = TimeMemory(
        title="候选图片",
        scene=TimeScene.MEETING,
        partition=DataPartition.WORK,
        status=MemoryStatus.COMPLETED,
    )
    evidence = Evidence(
        id=uuid4(),
        memory_id=memory.id,
        type=EvidenceType.VISUAL,
        content="候选图片",
        media_path=str(image_path),
    )
    repo = StubRepository(memory)

    class InvalidRefLLM(StubLLM):
        async def answer_query_multimodal(self, question, evidence_context, images):
            return {
                "answer": "图片2显示了答案",
                "confidence": "high",
                "used_evidence_refs": ["图片2"],
            }

    providers = SimpleNamespace(
        llm=lambda: InvalidRefLLM(),
        blob_store=lambda: StubBlobStore(),
    )
    engine = RankedEvidenceQueryEngine(repo, providers, evidence)

    async def retrieve_visual(*_args):
        return _visual_result(evidence)

    engine._retrieve = retrieve_visual

    result = await engine.query("图片是什么？", QueryScope.GLOBAL_WORK)

    assert result.status == QueryResultStatus.NOT_FOUND
    assert result.answer is None
    assert result.evidences[0].used_in_answer is False


@pytest.mark.asyncio
async def test_query_excludes_missing_visual_media():
    memory = TimeMemory(
        title="缺失关键帧",
        scene=TimeScene.MEETING,
        partition=DataPartition.WORK,
        status=MemoryStatus.COMPLETED,
    )
    evidence = Evidence(
        id=uuid4(),
        memory_id=memory.id,
        type=EvidenceType.VISUAL,
        content="不存在的图片",
        media_path="missing.png",
    )
    repo = StubRepository(memory)

    class MissingBlobStore(StubBlobStore):
        async def get_path(self, key):
            return None

    providers = SimpleNamespace(
        llm=lambda: StubLLM(),
        blob_store=lambda: MissingBlobStore(),
    )
    engine = RankedEvidenceQueryEngine(repo, providers, evidence)

    async def retrieve_visual(*_args):
        return _visual_result(evidence)

    engine._retrieve = retrieve_visual
    result = await engine.query("图片是什么？", QueryScope.GLOBAL_WORK)

    assert result.status == QueryResultStatus.NOT_FOUND
    assert result.evidences == []


def _visual_result(evidence):
    return RetrievedEvidence(text=[], visual=[evidence])
