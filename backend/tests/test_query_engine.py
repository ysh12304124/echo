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


class FixedRetrievedQueryEngine(QueryEngine):
    def __init__(self, repo, providers, retrieved):
        super().__init__(repo, providers)
        self.retrieved = retrieved

    async def _retrieve(self, _question, _scope, _memory_id, _space_id):
        return self.retrieved


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


@pytest.mark.asyncio
async def test_query_uses_visual_color_constraint_to_drop_conflicting_candidates(tmp_path):
    gray_path = tmp_path / "gray.png"
    black_path = tmp_path / "black.png"
    gray_path.write_bytes(b"gray")
    black_path.write_bytes(b"black")
    gray_memory = TimeMemory(
        title="灰色设备箱",
        scene=TimeScene.ONSITE,
        partition=DataPartition.WORK,
        status=MemoryStatus.COMPLETED,
    )
    black_memory = TimeMemory(
        title="黑色设备箱",
        scene=TimeScene.ONSITE,
        partition=DataPartition.WORK,
        status=MemoryStatus.COMPLETED,
    )
    gray_text = Evidence(
        id=uuid4(),
        memory_id=gray_memory.id,
        type=EvidenceType.TRANSCRIPT,
        content="另一只设备箱的记录是7241，存放位置改为B-08货架第三层。",
        metadata={"retrieval_score": 0.9, "source_confidence": "high"},
    )
    black_text = Evidence(
        id=uuid4(),
        memory_id=black_memory.id,
        type=EvidenceType.TRANSCRIPT,
        content="仓库这次先盘点到7421号设备箱，位置在B-03货架第二层。",
        metadata={"retrieval_score": 0.99, "source_confidence": "high"},
    )
    gray_visual = Evidence(
        id=uuid4(),
        memory_id=gray_memory.id,
        type=EvidenceType.VISUAL,
        content="灰色硬壳设备箱，资产贴纸显示 7241。",
        media_path=str(gray_path),
        metadata={"similarity_score": 0.48, "source_confidence": "high"},
    )
    black_visual = Evidence(
        id=uuid4(),
        memory_id=black_memory.id,
        type=EvidenceType.VISUAL,
        content="黑色硬壳设备箱，资产贴纸显示 7421。",
        media_path=str(black_path),
        metadata={"similarity_score": 0.46, "source_confidence": "high"},
    )
    repo = StubRepository(gray_memory)

    class CapturingLLM(StubLLM):
        def __init__(self):
            self.context = ""
            self.images = []

        async def answer_query_multimodal(self, question, evidence_context, images):
            self.context = evidence_context
            self.images = images
            return {
                "answer": "7241",
                "confidence": "high",
                "evidence_sufficient": True,
                "used_evidence_refs": ["文本1", "图片1"],
            }

    llm = CapturingLLM()
    providers = SimpleNamespace(
        llm=lambda: llm,
        blob_store=lambda: StubBlobStore(),
    )
    engine = FixedRetrievedQueryEngine(
        repo,
        providers,
        RetrievedEvidence(text=[black_text, gray_text], visual=[gray_visual, black_visual]),
    )

    result = await engine.query("灰色设备箱编号", QueryScope.GLOBAL_WORK)

    assert result.status == QueryResultStatus.CONFIRMED
    assert result.answer == "7241"
    assert "7241" in llm.context
    assert "7421" not in llm.context
    assert len(llm.images) == 1
    assert "灰色硬壳设备箱" in llm.images[0].caption


def _visual_result(evidence):
    return RetrievedEvidence(text=[], visual=[evidence])
