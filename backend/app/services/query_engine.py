from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.domain.enums import (
    ConfidenceLevel,
    EvidenceType,
    QueryResultStatus,
    QueryScope,
)
from app.domain.models import Evidence
from app.providers import ProviderFactory, get_provider_factory, get_settings
from app.providers.base import ImageInput, RerankCandidate
from app.repositories.memory_repo import MemoryRepository
from app.schemas import (
    QueryEvidenceResponse,
    QueryResponse,
    QuerySourceResponse,
)
from app.services.bm25 import BM25Document, BM25Index, normalize_scores
from app.services.keyframe_index import keyframe_blob_key


@dataclass(frozen=True)
class RetrievedEvidence:
    text: list[Evidence]
    visual: list[Evidence]


def retrieval_confidence(
    score: float, medium_score: float, high_score: float
) -> ConfidenceLevel:
    if score >= high_score:
        return ConfidenceLevel.HIGH
    if score >= medium_score:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


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
        retrieved = await self._retrieve(question, scope, memory_id, space_id)
        if not retrieved.text and not retrieved.visual:
            result = QueryResponse(query_id=query_id, status=QueryResultStatus.NOT_FOUND)
            await self._log(query_id, question, scope, result)
            return result

        settings = getattr(self.providers, "settings", get_settings())
        text_top = (
            retrieved.text
            if scope == QueryScope.MEMORY
            else retrieved.text[: settings.reranker_top_k]
        )
        blob = self.providers.blob_store()
        evidence_refs: dict[UUID, str] = {
            evidence.id: f"文本{index}"
            for index, evidence in enumerate(text_top, start=1)
        }
        visual_top: list[Evidence] = []
        images: list[ImageInput] = []
        visual_candidates = (
            retrieved.visual
            if scope == QueryScope.MEMORY
            else retrieved.visual[: settings.visual_retrieval_top_k]
        )
        for evidence in visual_candidates:
            if not evidence.media_path:
                continue
            path = await blob.get_path(evidence.media_path)
            if not path:
                continue
            ref = f"图片{len(visual_top) + 1}"
            visual_top.append(evidence)
            evidence_refs[evidence.id] = ref
            score = evidence.metadata.get("similarity_score")
            score_text = f"{float(score):.4f}" if score is not None else "未知"
            images.append(
                ImageInput(
                    path=path,
                    caption=(
                        f"{ref}: {evidence.content}; CLIP相关度={score_text}; "
                        f"相关性等级={evidence.confidence.value}"
                    ),
                )
            )

        top = text_top + visual_top
        if not top:
            result = QueryResponse(query_id=query_id, status=QueryResultStatus.NOT_FOUND)
            await self._log(query_id, question, scope, result)
            return result
        context_lines: list[str] = []
        for evidence in top:
            ref = evidence_refs[evidence.id]
            if evidence.type == EvidenceType.VISUAL:
                score = evidence.metadata.get("similarity_score")
                score_text = f"{float(score):.4f}" if score is not None else "未知"
                source_confidence = str(
                    evidence.metadata.get("source_confidence") or "未知"
                )
                context_lines.append(
                    f"[{ref}][visual] {evidence.content} "
                    f"(CLIP相关度={score_text}, 相关性等级={evidence.confidence.value}, "
                    f"关键帧质量={source_confidence}; 分数和等级仅供参考)"
                )
            else:
                score = evidence.metadata.get("retrieval_score")
                if score is not None:
                    source_confidence = str(
                        evidence.metadata.get("source_confidence") or "未知"
                    )
                    context_lines.append(
                        f"[{ref}][{evidence.type.value}] {evidence.content} "
                        f"(Reranker相关度={float(score):.4f}, "
                        f"相关性等级={evidence.confidence.value}, "
                        f"来源置信度={source_confidence}; 分数和等级仅供参考)"
                    )
                else:
                    context_lines.append(
                        f"[{ref}][{evidence.type.value}] {evidence.content} "
                        f"(来源置信度={evidence.confidence.value})"
                    )
        evidence_context = "\n".join(context_lines)

        llm = self.providers.llm()
        structured = await llm.answer_query_multimodal(
            question, evidence_context, images
        )
        answer = (structured.get("answer") or "").strip()
        llm_conf = str(structured.get("confidence") or "low").lower()
        if llm_conf not in {"high", "medium", "low"}:
            llm_conf = "low"

        allowed_refs = set(evidence_refs.values())
        raw_refs = structured.get("used_evidence_refs")
        refs_provided = isinstance(raw_refs, list)
        used_refs: list[str] = []
        invalid_refs = False
        if refs_provided:
            for item in raw_refs:
                ref = str(item).strip()
                if ref not in allowed_refs:
                    invalid_refs = True
                    continue
                if ref not in used_refs:
                    used_refs.append(ref)

        mentioned_image_refs = set(re.findall(r"图片\d+", answer))
        if not refs_provided:
            if mentioned_image_refs:
                used_refs = [
                    ref for ref in evidence_refs.values() if ref in mentioned_image_refs
                ]
            elif not visual_top:
                # Compatibility for legacy text-only providers.
                used_refs = [evidence_refs[evidence.id] for evidence in text_top]
        used_ref_set = set(used_refs)
        if (
            mentioned_image_refs - allowed_refs
            or mentioned_image_refs - used_ref_set
        ):
            invalid_refs = True
        evidence_sufficient = structured.get("evidence_sufficient", True) is True
        if answer in {"检索证据不足，无法回答", "证据不足，无法回答"}:
            answer = ""
        if answer and (invalid_refs or not used_refs or not evidence_sufficient):
            answer = ""
            llm_conf = "low"
            used_refs = []
            used_ref_set = set()

        selected = [
            evidence
            for evidence in top
            if evidence_refs[evidence.id] in used_ref_set
        ]
        used_ids = {evidence.id for evidence in selected}

        def ev_responses(items: list[Evidence]) -> list[QueryEvidenceResponse]:
            responses: list[QueryEvidenceResponse] = []
            for evidence in items[:8]:
                source_raw = evidence.metadata.get("source_confidence")
                source_confidence = None
                if source_raw:
                    try:
                        source_confidence = ConfidenceLevel(str(source_raw))
                    except ValueError:
                        source_confidence = None
                elif evidence.type != EvidenceType.VISUAL:
                    source_confidence = evidence.confidence
                score_raw = evidence.metadata.get(
                    "retrieval_score", evidence.metadata.get("similarity_score")
                )
                retrieval_score = (
                    float(score_raw) if score_raw is not None else None
                )
                responses.append(
                    QueryEvidenceResponse(
                        evidence_id=evidence.id,
                        type=evidence.type,
                        content=evidence.content,
                        confidence=evidence.confidence,
                        source_confidence=source_confidence,
                        retrieval_score=retrieval_score,
                        used_in_answer=evidence.id in used_ids,
                        media_url=(
                            blob.get_url(evidence.media_path)
                            if evidence.media_path
                            else None
                        ),
                        timestamp_ms=evidence.timestamp_ms,
                    )
                )
            return responses

        if answer:
            if llm_conf == "high":
                status = QueryResultStatus.CONFIRMED
                uncertainty = None
            else:
                status = QueryResultStatus.POSSIBLE
                uncertainty = "模型对答案把握不足，仅供参考"
            result = QueryResponse(
                query_id=query_id,
                status=status,
                answer=answer,
                evidences=ev_responses(top),
                sources=await self._sources(selected),
                uncertainty_reason=uncertainty,
            )
        else:
            result = QueryResponse(
                query_id=query_id,
                status=QueryResultStatus.NOT_FOUND,
                evidences=ev_responses(top),
                sources=await self._sources(top),
                uncertainty_reason="检索证据不足，无法回答",
            )

        await self._log(query_id, question, scope, result)
        return result

    async def _retrieve(
        self,
        question: str,
        scope: QueryScope,
        memory_id: UUID | None,
        space_id: UUID | None,
    ) -> RetrievedEvidence:
        if scope == QueryScope.MEMORY and memory_id:
            return await self._retrieve_memory(memory_id)
        scoped_evidences = await self._scoped_evidences(scope, memory_id, space_id)
        text = await self._retrieve_text(question, scope, scoped_evidences)
        visual = await self._retrieve_visual(
            question, scope, memory_id, space_id
        )
        return RetrievedEvidence(text=text, visual=visual)

    async def _retrieve_memory(self, memory_id: UUID) -> RetrievedEvidence:
        memory = await self.repo.get_time_memory(memory_id)
        if not memory:
            return RetrievedEvidence(text=[], visual=[])

        text = [
            evidence
            for evidence in await self.repo.list_evidences(memory_id)
            if evidence.type != EvidenceType.VISUAL
        ]
        visual: list[Evidence] = []
        for index, frame in enumerate(memory.key_frames):
            raw_path = str(frame.get("media_path") or frame.get("media_url") or "")
            media_path = keyframe_blob_key(raw_path)
            if not media_path:
                continue
            confidence_raw = str(frame.get("confidence") or "high")
            try:
                source_confidence = ConfidenceLevel(confidence_raw)
            except ValueError:
                source_confidence = ConfidenceLevel.HIGH
            visual.append(
                Evidence(
                    id=uuid5(
                        NAMESPACE_URL,
                        f"echo:keyframe:{memory.id}:{media_path}",
                    ),
                    memory_id=memory.id,
                    type=EvidenceType.VISUAL,
                    content=str(
                        frame.get("description")
                        or frame.get("label")
                        or f"关键帧 {index + 1}"
                    ),
                    media_path=media_path,
                    timestamp_ms=int(frame.get("timestamp_ms") or 0),
                    confidence=source_confidence,
                    metadata={"source_confidence": source_confidence.value},
                )
            )
        return RetrievedEvidence(text=text, visual=visual)

    async def _retrieve_text(
        self,
        question: str,
        scope: QueryScope,
        scoped_evidences: list[Evidence],
    ) -> list[Evidence]:
        settings = self.providers.settings
        if not scoped_evidences:
            return []

        embedding = self.providers.embedding()
        vector_store = self.providers.vector_store()
        q_vec = (await embedding.embed_query(question)).vector
        filt = {"partition": "work"} if scope == QueryScope.GLOBAL_WORK else None
        scored = await vector_store.search(
            q_vec,
            top_k=settings.reranker_candidates,
            filter=filt,
        )
        scoped_by_id = {str(evidence.id): evidence for evidence in scoped_evidences}
        vector_scores = {
            ev_id: score
            for ev_id, score, _meta in scored
            if ev_id in scoped_by_id
        }

        if settings.hybrid_retrieval_enabled:
            bm25 = BM25Index(
                [BM25Document(str(ev.id), ev.content) for ev in scoped_evidences],
                k1=settings.bm25_k1,
                b=settings.bm25_b,
            )
            bm25_scores = dict(bm25.search(question, settings.reranker_candidates))
            vector_norm = normalize_scores(vector_scores)
            bm25_norm = normalize_scores(bm25_scores)
            fused_scores = {
                ev_id: settings.hybrid_vector_weight * vector_norm.get(ev_id, 0.0)
                + settings.hybrid_bm25_weight * bm25_norm.get(ev_id, 0.0)
                for ev_id in set(vector_norm) | set(bm25_norm)
            }
            candidate_ids = [
                ev_id
                for ev_id, _score in sorted(
                    fused_scores.items(), key=lambda item: item[1], reverse=True
                )[: settings.reranker_candidates]
            ]
        else:
            candidate_ids = list(vector_scores)

        candidates = [
            (scoped_by_id[ev_id], vector_scores.get(ev_id, 0.0))
            for ev_id in candidate_ids
            if ev_id in scoped_by_id
        ]
        if not candidates:
            return []
        if not settings.reranker_enabled:
            return [ev for ev, _score in candidates[: settings.reranker_top_k]]

        reranked = await self.providers.reranker().rerank(
            question,
            [RerankCandidate(id=str(ev.id), document=ev.content) for ev, _ in candidates],
        )
        scores = {item.id: item.score for item in reranked}
        ranked = [
            (ev, scores[str(ev.id)])
            for ev, _ in candidates
            if str(ev.id) in scores and scores[str(ev.id)] >= settings.reranker_min_score
        ]
        ranked.sort(key=lambda item: item[1], reverse=True)
        results: list[Evidence] = []
        for evidence, score in ranked[: settings.reranker_top_k]:
            results.append(
                evidence.model_copy(
                    update={
                        "confidence": retrieval_confidence(
                            score,
                            settings.reranker_medium_score,
                            settings.reranker_high_score,
                        ),
                        "metadata": {
                            **evidence.metadata,
                            "source_confidence": evidence.confidence.value,
                            "retrieval_score": score,
                        },
                    }
                )
            )
        return results

    async def _retrieve_visual(
        self,
        question: str,
        scope: QueryScope,
        memory_id: UUID | None,
        space_id: UUID | None,
    ) -> list[Evidence]:
        settings = self.providers.settings
        if not settings.visual_retrieval_enabled:
            return []
        store = self.providers.visual_vector_store()
        info = await store.index_info()
        if info is None or info.count == 0:
            return []

        allowed_memory_ids = await self._scope_memory_ids(
            scope, memory_id, space_id
        )
        filter_metadata = (
            {"partition": "work"} if scope == QueryScope.GLOBAL_WORK else None
        )
        query_vector = (
            await self.providers.visual_embedding().embed_text(question)
        ).vector
        rows = await store.search(
            query_vector,
            top_k=settings.visual_retrieval_candidates,
            filter=filter_metadata,
        )
        results: list[Evidence] = []
        for entry_id, score, metadata in rows:
            if score < settings.visual_retrieval_min_score:
                continue
            item_memory_id = str(metadata.get("memory_id") or "")
            if allowed_memory_ids is not None and item_memory_id not in allowed_memory_ids:
                continue
            try:
                source_confidence = ConfidenceLevel(
                    str(metadata.get("confidence") or "high")
                )
                evidence_id = UUID(entry_id)
                evidence_memory_id = UUID(item_memory_id)
            except (ValueError, TypeError):
                continue
            results.append(
                Evidence(
                    id=evidence_id,
                    memory_id=evidence_memory_id,
                    type="visual",
                    content=str(metadata.get("content") or "关键帧"),
                    media_path=str(metadata.get("media_path") or "") or None,
                    timestamp_ms=int(metadata.get("timestamp_ms") or 0),
                    confidence=retrieval_confidence(
                        score,
                        settings.visual_retrieval_medium_score,
                        settings.visual_retrieval_high_score,
                    ),
                    metadata={
                        **metadata,
                        "source_confidence": source_confidence.value,
                        "similarity_score": score,
                    },
                )
            )
            if len(results) >= settings.visual_retrieval_top_k:
                break
        return results

    async def _scope_memory_ids(
        self,
        scope: QueryScope,
        memory_id: UUID | None,
        space_id: UUID | None,
    ) -> set[str] | None:
        if scope == QueryScope.GLOBAL_WORK:
            return None
        if scope == QueryScope.MEMORY:
            return {str(memory_id)} if memory_id else set()
        if scope == QueryScope.SPACE and space_id:
            return await self._space_related_memory_ids(space_id)
        return set()

    async def _space_related_memory_ids(self, space_id: UUID) -> set[str]:
        space = await self.repo.get_space_memory(space_id)
        if not space:
            return set()
        related_memory_ids: set[str] = set()
        for anchor in space.anchors:
            related_memory_ids.update(str(item) for item in anchor.related_memory_ids)
        for binding in await self.repo.list_bindings(space_memory_id=space_id):
            if binding.time_memory_id:
                related_memory_ids.add(str(binding.time_memory_id))
        return related_memory_ids

    async def _scoped_evidences(
        self,
        scope: QueryScope,
        memory_id: UUID | None,
        space_id: UUID | None,
    ) -> list[Evidence]:
        if scope == QueryScope.MEMORY and memory_id:
            return await self.repo.list_evidences(memory_id)
        if scope == QueryScope.SPACE and space_id:
            related_memory_ids = await self._space_related_memory_ids(space_id)
            evidences = []
            for related_id in related_memory_ids:
                evidences.extend(await self.repo.list_evidences(UUID(related_id)))
            return evidences
        return await self.repo.list_all_work_evidences()

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
