from __future__ import annotations

from uuid import UUID, uuid4

from app.domain.enums import (
    ConfidenceLevel,
    QueryResultStatus,
    QueryScope,
)
from app.domain.models import Evidence
from app.providers import ProviderFactory, get_provider_factory
from app.repositories.memory_repo import MemoryRepository
from app.schemas import (
    QueryEvidenceResponse,
    QueryResponse,
    QuerySourceResponse,
)

# 检索规模：单机 MVP 下取较大 top-k 以保证召回；本地部署可按需下调。
RETRIEVAL_TOP_K = 50
CONTEXT_LIMIT = 8


class QueryEngine:
    def __init__(self, repo: MemoryRepository, providers: ProviderFactory | None = None):
        self.repo = repo
        self.providers = providers or get_provider_factory()

    async def query(
        self,
        question: str,
        scope: QueryScope,
        memory_id: UUID | None = None,
        space_id: UUID | None = None,
    ) -> QueryResponse:
        query_id = uuid4()

        if scope == QueryScope.MEMORY and not memory_id:
            return QueryResponse(
                query_id=query_id,
                status=QueryResultStatus.NOT_FOUND,
                uncertainty_reason="请先选择一段记忆",
            )
        if scope == QueryScope.SPACE and not space_id:
            return QueryResponse(
                query_id=query_id,
                status=QueryResultStatus.NOT_FOUND,
                uncertainty_reason="请先选择一个空间",
            )

        # 真实 RAG：问题向量化 → 按 scope 检索 → 证据接地问答。
        ranked = await self._retrieve(question, scope, memory_id, space_id)
        if not ranked:
            result = QueryResponse(query_id=query_id, status=QueryResultStatus.NOT_FOUND)
            await self._log(query_id, question, scope, result)
            return result

        top = ranked[:CONTEXT_LIMIT]
        evidence_context = "\n".join(
            f"[{e.type.value}] {e.content} (confidence={e.confidence.value})" for e in top
        )

        llm = self.providers.llm()
        structured = await llm.answer_query_structured(question, evidence_context)
        answer = (structured.get("answer") or "").strip()
        llm_conf = structured.get("confidence", "low")

        high_conf = [e for e in top if e.confidence == ConfidenceLevel.HIGH]
        low_conf = [e for e in top if e.confidence != ConfidenceLevel.HIGH]
        blob = self.providers.blob_store()

        def ev_responses(items: list[Evidence]) -> list[QueryEvidenceResponse]:
            return [
                QueryEvidenceResponse(
                    evidence_id=e.id,
                    type=e.type,
                    content=e.content,
                    confidence=e.confidence,
                    media_url=blob.get_url(e.media_path) if e.media_path else None,
                    timestamp_ms=e.timestamp_ms,
                )
                for e in items[:5]
            ]

        if answer:
            if high_conf and llm_conf != "low":
                # 确认：有确定答案 + 高置信证据
                status = QueryResultStatus.CONFIRMED
                shown = high_conf
                uncertainty = None
                shown_answer = answer
            else:
                # 可能：有答案但仅低置信证据或模型不确定
                status = QueryResultStatus.POSSIBLE
                shown = low_conf or top
                uncertainty = "证据置信度不足，仅供参考"
                shown_answer = answer
            result = QueryResponse(
                query_id=query_id,
                status=status,
                answer=shown_answer,
                evidences=ev_responses(shown),
                sources=await self._sources(shown or top),
                uncertainty_reason=uncertainty,
            )
        else:
            # 无接地答案。若存在低置信证据 → 可能；否则 → 没有找到。
            if low_conf:
                result = QueryResponse(
                    query_id=query_id,
                    status=QueryResultStatus.POSSIBLE,
                    evidences=ev_responses(low_conf),
                    sources=await self._sources(low_conf),
                    uncertainty_reason="无法确认相关信息",
                )
            else:
                result = QueryResponse(
                    query_id=query_id, status=QueryResultStatus.NOT_FOUND
                )

        await self._log(query_id, question, scope, result)
        return result

    async def _retrieve(
        self,
        question: str,
        scope: QueryScope,
        memory_id: UUID | None,
        space_id: UUID | None,
    ) -> list[Evidence]:
        embedding = self.providers.embedding()
        vector_store = self.providers.vector_store()
        q_vec = (await embedding.embed_query(question)).vector

        related_memory_ids: set[str] | None = None
        filt: dict | None
        if scope == QueryScope.MEMORY and memory_id:
            filt = {"memory_id": str(memory_id)}
        elif scope == QueryScope.SPACE and space_id:
            space = await self.repo.get_space_memory(space_id)
            if not space:
                return []
            related_memory_ids = set()
            for anchor in space.anchors:
                related_memory_ids.update(str(m) for m in anchor.related_memory_ids)
            # 叠加候选/确认的时空绑定所关联的时间记忆
            for b in await self.repo.list_bindings(space_memory_id=space_id):
                if b.time_memory_id:
                    related_memory_ids.add(str(b.time_memory_id))
            filt = None
        else:
            # GLOBAL_WORK：严格排除 quality_time 分区
            filt = {"partition": "work"}

        scored = await vector_store.search(q_vec, top_k=RETRIEVAL_TOP_K, filter=filt)

        evidences: list[Evidence] = []
        for ev_id, _score, meta in scored:
            if related_memory_ids is not None:
                if meta.get("memory_id") not in related_memory_ids:
                    continue
            ev = await self.repo.get_evidence(UUID(ev_id))
            if ev:
                evidences.append(ev)
        return evidences

    async def _sources(self, evidences: list[Evidence]) -> list[QuerySourceResponse]:
        sources: list[QuerySourceResponse] = []
        seen: set[UUID] = set()
        for e in evidences:
            if e.memory_id in seen:
                continue
            memory = await self.repo.get_time_memory(e.memory_id)
            if not memory:
                continue
            seen.add(e.memory_id)
            sources.append(
                QuerySourceResponse(
                    memory_id=memory.id,
                    memory_title=memory.title or memory.identify_brief,
                    scene=memory.scene,
                    time_offset_seconds=e.timestamp_ms // 1000,
                )
            )
            if len(sources) >= 3:
                break
        return sources

    async def _log(
        self, query_id: UUID, question: str, scope: QueryScope, result: QueryResponse
    ):
        await self.repo.save_query_log(
            query_id,
            question,
            scope.value,
            result.status.value,
            result.answer,
            result.model_dump(mode="json"),
        )
