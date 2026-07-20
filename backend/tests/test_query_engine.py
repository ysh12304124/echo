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
from app.services.query_engine import QueryEngine


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


class StubBlobStore:
    def get_url(self, key):
        return key


class RankedEvidenceQueryEngine(QueryEngine):
    def __init__(self, repo, providers, evidence):
        super().__init__(repo, providers)
        self.evidence = evidence

    async def _retrieve(self, _question, _scope, _memory_id, _space_id):
        return [self.evidence]


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
