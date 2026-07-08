from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from app.domain.enums import (
    BindingType,
    ConfidenceLevel,
    DataPartition,
    EventType,
    EvidenceType,
    MemoryStatus,
    MemoryType,
    SpaceQuality,
    TimeScene,
)
from app.domain.models import (
    Binding,
    Entity,
    Event,
    Evidence,
    IngestSession,
    SpaceAnchor,
    SpaceMemory,
    TimeMemory,
)
from app.providers import ProviderFactory, get_provider_factory
from app.repositories.memory_repo import MemoryRepository
from app.services.memory_builder import MemoryBuilder
from app.services.person_service import PersonService


def _confidence(value: str, default: ConfidenceLevel = ConfidenceLevel.MEDIUM) -> ConfidenceLevel:
    try:
        return ConfidenceLevel(value)
    except (ValueError, TypeError):
        return default


class IngestPipeline:
    def __init__(self, repo: MemoryRepository, providers: ProviderFactory | None = None):
        self.repo = repo
        self.providers = providers or get_provider_factory()
        self.memory_builder = MemoryBuilder(self.providers)
        self.person_service = PersonService(repo)

    async def create_session(
        self,
        memory_type: MemoryType,
        scene: TimeScene | None = None,
        partition: DataPartition = DataPartition.WORK,
        title: str = "",
    ) -> IngestSession:
        if memory_type == MemoryType.TIME and scene is None:
            scene = TimeScene.MEETING
        # 分区强制以 scene 为准，杜绝非法组合（Quality Time 必须隔离）。
        if scene == TimeScene.QUALITY_TIME:
            partition = DataPartition.QUALITY_TIME
        elif scene in (TimeScene.MEETING, TimeScene.ONSITE):
            if partition == DataPartition.QUALITY_TIME:
                raise ValueError("工作场景（meeting/onsite）不能归入 quality_time 分区")
            partition = DataPartition.WORK

        session = IngestSession(
            memory_type=memory_type,
            scene=scene,
            partition=partition,
            status=MemoryStatus.RECORDING,
            title=title,
        )
        await self.repo.create_session(session)
        return session

    async def upload_frame(
        self, session_id: UUID, data: bytes, timestamp_ms: int, is_key_moment: bool = False
    ) -> tuple[UUID, bool, bool]:
        session = await self.repo.get_session(session_id)
        if not session:
            raise ValueError("Session not found")

        blob = self.providers.blob_store()
        vision = self.providers.vision()
        key = f"sessions/{session_id}/frames/{uuid4()}.jpg"
        path = await blob.save(key, data, "image/jpeg")

        keep = await vision.should_keep_frame(path)
        if not keep:
            return uuid4(), False, True

        await self.repo.update_session_frames(session_id, path)
        return UUID(key.split("/")[-1].replace(".jpg", "")), True, False

    async def upload_audio(self, session_id: UUID, data: bytes, timestamp_ms: int) -> UUID:
        session = await self.repo.get_session(session_id)
        if not session:
            raise ValueError("Session not found")

        blob = self.providers.blob_store()
        key = f"sessions/{session_id}/audio/{uuid4()}.pcm"
        path = await blob.save(key, data, "audio/pcm")
        await self.repo.update_session_audio(session_id, path)
        return uuid4()

    async def complete_session(self, session_id: UUID) -> TimeMemory | SpaceMemory:
        session = await self.repo.get_session(session_id)
        if not session:
            raise ValueError("Session not found")

        frame_paths, audio_paths = await self.repo.get_session_media_paths(session_id)

        if session.memory_type == MemoryType.TIME:
            return await self._process_time_session(session, frame_paths, audio_paths)
        else:
            return await self._process_space_session(session, frame_paths)

    async def _process_time_session(
        self, session: IngestSession, frame_paths: list[str], audio_paths: list[str]
    ) -> TimeMemory:
        memory = TimeMemory(
            scene=session.scene or TimeScene.MEETING,
            partition=session.partition,
            status=MemoryStatus.PROCESSING,
            started_at=session.created_at,
            ended_at=datetime.utcnow(),
            session_id=session.id,
            title=session.title,
        )
        await self.repo.create_time_memory(memory)
        await self.repo.link_session_memory(session.id, memory.id, MemoryStatus.PROCESSING)

        asr = self.providers.asr()
        vision = self.providers.vision()
        ocr = self.providers.ocr()
        llm = self.providers.llm()
        embedding = self.providers.embedding()
        vector_store = self.providers.vector_store()
        blob = self.providers.blob_store()

        all_transcript = []
        for audio_path in audio_paths:
            segments = await asr.transcribe(audio_path)
            for seg in segments:
                if seg.confidence >= 0.85:
                    seg_conf = ConfidenceLevel.HIGH
                elif seg.confidence >= 0.6:
                    seg_conf = ConfidenceLevel.MEDIUM
                else:
                    seg_conf = ConfidenceLevel.LOW
                ev = Evidence(
                    memory_id=memory.id,
                    type=EvidenceType.TRANSCRIPT,
                    content=seg.text,
                    timestamp_ms=seg.start_ms,
                    confidence=seg_conf,
                    metadata={"speaker_id": seg.speaker_id or "unknown"},
                )
                await self.repo.save_evidence(ev)
                all_transcript.append(seg.text)
                emb = await embedding.embed(seg.text)
                await vector_store.upsert(
                    str(ev.id),
                    emb.vector,
                    {"memory_id": str(memory.id), "partition": memory.partition.value, "type": "transcript"},
                )

        for i, frame_path in enumerate(frame_paths):
            vis = await vision.analyze_frame(frame_path)
            if not vis.is_informative:
                continue
            ev = Evidence(
                memory_id=memory.id,
                type=EvidenceType.VISUAL,
                content=vis.summary,
                media_path=frame_path,
                timestamp_ms=i * 2000,
                confidence=ConfidenceLevel.HIGH,
            )
            await self.repo.save_evidence(ev)
            emb = await embedding.embed(vis.summary)
            await vector_store.upsert(
                str(ev.id),
                emb.vector,
                {"memory_id": str(memory.id), "partition": memory.partition.value, "type": "visual"},
            )

            ocr_result = await ocr.extract_text(frame_path)
            if ocr_result.text:
                ocr_ev = Evidence(
                    memory_id=memory.id,
                    type=EvidenceType.OCR,
                    content=ocr_result.text,
                    media_path=frame_path,
                    timestamp_ms=i * 2000,
                    confidence=ConfidenceLevel.HIGH if ocr_result.confidence >= 0.8 else ConfidenceLevel.MEDIUM,
                )
                await self.repo.save_evidence(ocr_ev)
                emb = await embedding.embed(ocr_result.text)
                await vector_store.upsert(
                    str(ocr_ev.id),
                    emb.vector,
                    {"memory_id": str(memory.id), "partition": memory.partition.value, "type": "ocr"},
                )

        transcript_text = " ".join(all_transcript)
        # 视觉/OCR 摘要也纳入抽取上下文，提升实体/事件召回。
        visual_context = " ".join(
            e.content for e in await self.repo.list_evidences(memory.id)
            if e.type in (EvidenceType.VISUAL, EvidenceType.OCR)
        )
        scene_value = session.scene.value if session.scene else "meeting"
        extract_context = (transcript_text + "\n" + visual_context).strip()

        events_data = await llm.extract_events(extract_context, scene_value)
        for ed in events_data:
            try:
                et = EventType(ed["type"])
            except (ValueError, KeyError):
                et = EventType.BUSINESS_SEMANTIC
            event = Event(
                memory_id=memory.id,
                event_type=et,
                start_ms=ed.get("start_ms", 0),
                label=ed.get("label", ""),
                confidence=_confidence(ed.get("confidence", "medium")),
            )
            await self.repo.save_event(event)

        # 实体/人物抽取（无硬编码）：LLM 产出候选，跨记忆按名+分区归并，禁跨分区。
        entities_data = await llm.extract_entities(extract_context, scene_value)
        for en in entities_data:
            name = (en.get("name") or "").strip()
            if not name:
                continue
            etype = (en.get("type") or "person").strip()
            conf = _confidence(en.get("confidence", "low"))
            if etype == "person":
                await self.person_service.ensure_person(
                    name=name,
                    partition=memory.partition,
                    memory_id=memory.id,
                    confidence=conf,
                    role=en.get("role"),
                )
            else:
                existing = await self.repo.find_entity(name, etype, memory.partition)
                if existing:
                    if memory.id not in existing.memory_ids:
                        existing.memory_ids.append(memory.id)
                        await self.repo.update_entity(
                            existing.id, memory_ids=existing.memory_ids
                        )
                else:
                    await self.repo.save_entity(
                        Entity(
                            entity_type=etype,
                            name=name,
                            partition=memory.partition,
                            confidence=conf,
                            memory_ids=[memory.id],
                        )
                    )

        # 并行时空候选绑定：同分区、时间窗重叠的空间记忆生成候选绑定，待用户确认。
        await self._create_candidate_bindings(memory)

        identify_brief = await self.memory_builder.build_identify_brief(memory, transcript_text)
        nav_summary = await self.memory_builder.build_navigation_summary(memory, transcript_text)

        duration = int((datetime.utcnow() - session.created_at).total_seconds())
        memory = await self.repo.update_time_memory(
            memory.id,
            status=MemoryStatus.COMPLETED,
            identify_brief=identify_brief,
            navigation_summary=nav_summary,
            evidence_status="ready",
            duration_seconds=duration,
            title=memory.title or identify_brief,
            ended_at=datetime.utcnow(),
        )
        await self.repo.link_session_memory(session.id, memory.id, MemoryStatus.COMPLETED)
        return memory

    async def _create_candidate_bindings(self, memory: TimeMemory) -> None:
        """为并行采集的空间记忆生成候选时空绑定（同分区 + 时间窗重叠）。"""
        if not memory.started_at or not memory.ended_at:
            return
        spaces, _ = await self.repo.list_space_memories(partition=memory.partition)
        for space in spaces:
            if not space.captured_at:
                continue
            # 空间采集时间落在时间记忆窗口内视为并行
            if memory.started_at <= space.captured_at <= memory.ended_at:
                existing = await self.repo.list_bindings(
                    time_memory_id=memory.id, space_memory_id=space.id
                )
                if existing:
                    continue
                await self.repo.save_binding(
                    Binding(
                        binding_type=BindingType.CANDIDATE,
                        time_memory_id=memory.id,
                        space_memory_id=space.id,
                        confidence=ConfidenceLevel.LOW,
                        user_confirmed=False,
                    )
                )

    async def _process_space_session(
        self, session: IngestSession, frame_paths: list[str]
    ) -> SpaceMemory:
        reconstruction = self.providers.reconstruction()
        result = await reconstruction.reconstruct(frame_paths)

        quality_map = {
            "excellent": SpaceQuality.EXCELLENT,
            "good": SpaceQuality.GOOD,
            "retry_required": SpaceQuality.RETRY_REQUIRED,
        }
        quality = quality_map.get(result.quality, SpaceQuality.GOOD)

        anchors = [
            SpaceAnchor(
                space_id=uuid4(),
                name=s["name"],
                anchor_type=s.get("type", "generic"),
                position=s.get("position", {"x": 0, "y": 0, "z": 0}),
            )
            for s in result.anchor_suggestions
        ]

        memory = SpaceMemory(
            partition=session.partition,
            status=MemoryStatus.COMPLETED if quality != SpaceQuality.RETRY_REQUIRED else MemoryStatus.FAILED,
            quality=quality,
            model_url=result.model_url,
            anchors=anchors,
            captured_at=datetime.utcnow(),
            identify_brief=session.title or "空间采集",
            session_id=session.id,
            title=session.title or "空间记忆",
        )
        for a in anchors:
            a.space_id = memory.id

        await self.repo.create_space_memory(memory)
        await self.repo.link_session_memory(session.id, memory.id, memory.status)
        return memory
