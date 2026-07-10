import json
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import (
    BindingType,
    ConfidenceLevel,
    DataPartition,
    EntityType,
    MemoryStatus,
    MemoryType,
    TimeScene,
)
from app.domain.models import (
    Binding,
    Entity,
    Evidence,
    Event,
    IngestSession,
    NavigationSummary,
    Person,
    SpaceAnchor,
    SpaceMemory,
    TimeMemory,
)
from app.repositories.database import (
    BindingORM,
    EntityORM,
    EvidenceORM,
    EventORM,
    PersonORM,
    QueryLogORM,
    SessionORM,
    SpaceMemoryORM,
    TimeMemoryORM,
)


def _parse_json(s: str, default=None):
    if default is None:
        default = []
    try:
        return json.loads(s) if s else default
    except json.JSONDecodeError:
        return default


class MemoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Sessions ---
    async def create_session(self, session: IngestSession) -> IngestSession:
        orm = SessionORM(
            id=str(session.id),
            memory_type=session.memory_type.value,
            scene=session.scene.value if session.scene else None,
            partition=session.partition.value,
            status=session.status.value,
            memory_id=str(session.memory_id) if session.memory_id else None,
            title=session.title,
            created_at=session.created_at,
        )
        self.db.add(orm)
        await self.db.commit()
        return session

    async def get_session(self, session_id: UUID) -> Optional[IngestSession]:
        result = await self.db.execute(
            select(SessionORM).where(SessionORM.id == str(session_id))
        )
        orm = result.scalar_one_or_none()
        if not orm:
            return None
        return IngestSession(
            id=UUID(orm.id),
            memory_type=MemoryType(orm.memory_type),
            scene=TimeScene(orm.scene) if orm.scene else None,
            partition=DataPartition(orm.partition),
            status=MemoryStatus(orm.status),
            memory_id=UUID(orm.memory_id) if orm.memory_id else None,
            title=orm.title,
            created_at=orm.created_at,
            frame_count=orm.frame_count,
            audio_chunk_count=orm.audio_chunk_count,
        )

    async def update_session_frames(self, session_id: UUID, frame_path: str):
        result = await self.db.execute(
            select(SessionORM).where(SessionORM.id == str(session_id))
        )
        orm = result.scalar_one_or_none()
        if orm:
            paths = _parse_json(orm.frame_paths)
            paths.append(frame_path)
            orm.frame_paths = json.dumps(paths)
            orm.frame_count = len(paths)
            await self.db.commit()

    async def update_session_audio(self, session_id: UUID, audio_path: str):
        result = await self.db.execute(
            select(SessionORM).where(SessionORM.id == str(session_id))
        )
        orm = result.scalar_one_or_none()
        if orm:
            paths = _parse_json(orm.audio_paths)
            paths.append(audio_path)
            orm.audio_paths = json.dumps(paths)
            orm.audio_chunk_count = len(paths)
            await self.db.commit()

    async def get_session_media_paths(self, session_id: UUID) -> tuple[list[str], list[str]]:
        result = await self.db.execute(
            select(SessionORM).where(SessionORM.id == str(session_id))
        )
        orm = result.scalar_one_or_none()
        if not orm:
            return [], []
        return _parse_json(orm.frame_paths), _parse_json(orm.audio_paths)

    async def link_session_memory(self, session_id: UUID, memory_id: UUID, status: MemoryStatus):
        await self.db.execute(
            update(SessionORM)
            .where(SessionORM.id == str(session_id))
            .values(memory_id=str(memory_id), status=status.value)
        )
        await self.db.commit()

    # --- Time Memories ---
    async def create_time_memory(self, memory: TimeMemory) -> TimeMemory:
        orm = TimeMemoryORM(
            id=str(memory.id),
            title=memory.title,
            scene=memory.scene.value,
            partition=memory.partition.value,
            status=memory.status.value,
            started_at=memory.started_at,
            ended_at=memory.ended_at,
            duration_seconds=memory.duration_seconds,
            identify_brief=memory.identify_brief,
            navigation_summary=(
                memory.navigation_summary.model_dump_json()
                if memory.navigation_summary
                else None
            ),
            key_frames=json.dumps(memory.key_frames),
            evidence_status=memory.evidence_status,
            is_favorited=memory.is_favorited,
            is_locked=memory.is_locked,
            user_note=memory.user_note,
            session_id=str(memory.session_id) if memory.session_id else None,
        )
        self.db.add(orm)
        await self.db.commit()
        return memory

    async def get_time_memory(self, memory_id: UUID) -> Optional[TimeMemory]:
        result = await self.db.execute(
            select(TimeMemoryORM).where(TimeMemoryORM.id == str(memory_id))
        )
        orm = result.scalar_one_or_none()
        if not orm:
            return None
        nav = None
        if orm.navigation_summary:
            nav = NavigationSummary.model_validate_json(orm.navigation_summary)
        return TimeMemory(
            id=UUID(orm.id),
            title=orm.title,
            scene=TimeScene(orm.scene),
            partition=DataPartition(orm.partition),
            status=MemoryStatus(orm.status),
            started_at=orm.started_at,
            ended_at=orm.ended_at,
            duration_seconds=orm.duration_seconds,
            identify_brief=orm.identify_brief,
            navigation_summary=nav,
            key_frames=_parse_json(orm.key_frames),
            evidence_status=orm.evidence_status,
            is_favorited=orm.is_favorited,
            is_locked=orm.is_locked,
            user_note=orm.user_note,
            session_id=UUID(orm.session_id) if orm.session_id else None,
        )

    async def list_time_memories(
        self,
        partition: Optional[DataPartition] = None,
        scene: Optional[TimeScene] = None,
        status: Optional[MemoryStatus] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[TimeMemory], int]:
        query = select(TimeMemoryORM)
        if partition:
            query = query.where(TimeMemoryORM.partition == partition.value)
        if scene:
            query = query.where(TimeMemoryORM.scene == scene.value)
        if status:
            query = query.where(TimeMemoryORM.status == status.value)
        query = query.order_by(desc(TimeMemoryORM.started_at), desc(TimeMemoryORM.id))
        result = await self.db.execute(query)
        all_rows = result.scalars().all()
        total = len(all_rows)
        rows = all_rows[offset : offset + limit]
        memories = []
        for orm in rows:
            nav = None
            if orm.navigation_summary:
                nav = NavigationSummary.model_validate_json(orm.navigation_summary)
            memories.append(
                TimeMemory(
                    id=UUID(orm.id),
                    title=orm.title,
                    scene=TimeScene(orm.scene),
                    partition=DataPartition(orm.partition),
                    status=MemoryStatus(orm.status),
                    started_at=orm.started_at,
                    ended_at=orm.ended_at,
                    duration_seconds=orm.duration_seconds,
                    identify_brief=orm.identify_brief,
                    navigation_summary=nav,
                    key_frames=_parse_json(orm.key_frames),
                    evidence_status=orm.evidence_status,
                    is_favorited=orm.is_favorited,
                    is_locked=orm.is_locked,
                    session_id=UUID(orm.session_id) if orm.session_id else None,
                )
            )
        return memories, total

    async def update_time_memory(self, memory_id: UUID, **kwargs) -> Optional[TimeMemory]:
        values = {}
        for k, v in kwargs.items():
            if v is not None:
                if k == "navigation_summary" and isinstance(v, NavigationSummary):
                    values[k] = v.model_dump_json()
                elif k == "key_frames" and isinstance(v, list):
                    values[k] = json.dumps(v)
                elif hasattr(v, "value"):
                    values[k] = v.value
                else:
                    values[k] = v
        if values:
            await self.db.execute(
                update(TimeMemoryORM)
                .where(TimeMemoryORM.id == str(memory_id))
                .values(**values)
            )
            await self.db.commit()
        return await self.get_time_memory(memory_id)

    async def delete_time_memory(self, memory_id: UUID):
        await self.db.execute(delete(EvidenceORM).where(EvidenceORM.memory_id == str(memory_id)))
        await self.db.execute(delete(EventORM).where(EventORM.memory_id == str(memory_id)))
        await self.db.execute(
            delete(BindingORM).where(BindingORM.time_memory_id == str(memory_id))
        )
        await self.db.execute(delete(TimeMemoryORM).where(TimeMemoryORM.id == str(memory_id)))
        await self.db.commit()

    # --- Space Memories ---
    async def create_space_memory(self, memory: SpaceMemory) -> SpaceMemory:
        orm = SpaceMemoryORM(
            id=str(memory.id),
            title=memory.title,
            partition=memory.partition.value,
            status=memory.status.value,
            quality=memory.quality.value if memory.quality else None,
            model_url=memory.model_url,
            anchors=json.dumps([a.model_dump(mode="json") for a in memory.anchors]),
            captured_at=memory.captured_at,
            identify_brief=memory.identify_brief,
            is_favorited=memory.is_favorited,
            session_id=str(memory.session_id) if memory.session_id else None,
        )
        self.db.add(orm)
        await self.db.commit()
        return memory

    async def get_space_memory(self, space_id: UUID) -> Optional[SpaceMemory]:
        result = await self.db.execute(
            select(SpaceMemoryORM).where(SpaceMemoryORM.id == str(space_id))
        )
        orm = result.scalar_one_or_none()
        if not orm:
            return None
        anchors_data = _parse_json(orm.anchors, [])
        anchors = [SpaceAnchor(**{**a, "id": UUID(a["id"]) if isinstance(a.get("id"), str) else a.get("id")}) for a in anchors_data]
        from app.domain.enums import SpaceQuality
        return SpaceMemory(
            id=UUID(orm.id),
            title=orm.title,
            partition=DataPartition(orm.partition),
            status=MemoryStatus(orm.status),
            quality=SpaceQuality(orm.quality) if orm.quality else None,
            model_url=orm.model_url,
            anchors=anchors,
            captured_at=orm.captured_at,
            identify_brief=orm.identify_brief,
            is_favorited=orm.is_favorited,
            session_id=UUID(orm.session_id) if orm.session_id else None,
        )

    async def list_space_memories(
        self, partition: Optional[DataPartition] = None
    ) -> tuple[list[SpaceMemory], int]:
        query = select(SpaceMemoryORM)
        if partition:
            query = query.where(SpaceMemoryORM.partition == partition.value)
        result = await self.db.execute(query)
        rows = result.scalars().all()
        spaces = []
        for orm in rows:
            space = await self.get_space_memory(UUID(orm.id))
            if space:
                spaces.append(space)
        return spaces, len(spaces)

    async def update_space_memory(self, space_id: UUID, **kwargs) -> Optional[SpaceMemory]:
        values = {}
        for k, v in kwargs.items():
            if v is None:
                continue
            if hasattr(v, "value"):
                values[k] = v.value
            else:
                values[k] = v
        if values:
            await self.db.execute(
                update(SpaceMemoryORM).where(SpaceMemoryORM.id == str(space_id)).values(**values)
            )
            await self.db.commit()
        return await self.get_space_memory(space_id)

    async def delete_space_memory(self, space_id: UUID):
        await self.db.execute(
            delete(BindingORM).where(BindingORM.space_memory_id == str(space_id))
        )
        await self.db.execute(delete(SpaceMemoryORM).where(SpaceMemoryORM.id == str(space_id)))
        await self.db.commit()

    # --- Evidence ---
    async def save_evidence(self, evidence: Evidence) -> Evidence:
        orm = EvidenceORM(
            id=str(evidence.id),
            memory_id=str(evidence.memory_id),
            event_id=str(evidence.event_id) if evidence.event_id else None,
            type=evidence.type.value,
            content=evidence.content,
            media_path=evidence.media_path,
            timestamp_ms=evidence.timestamp_ms,
            confidence=evidence.confidence.value,
            meta_json=json.dumps(evidence.metadata),
        )
        self.db.add(orm)
        await self.db.commit()
        return evidence

    async def list_evidences(self, memory_id: UUID) -> list[Evidence]:
        result = await self.db.execute(
            select(EvidenceORM).where(EvidenceORM.memory_id == str(memory_id))
        )
        rows = result.scalars().all()
        from app.domain.enums import ConfidenceLevel, EvidenceType
        return [
            Evidence(
                id=UUID(r.id),
                memory_id=UUID(r.memory_id),
                event_id=UUID(r.event_id) if r.event_id else None,
                type=EvidenceType(r.type),
                content=r.content,
                media_path=r.media_path,
                timestamp_ms=r.timestamp_ms,
                confidence=ConfidenceLevel(r.confidence),
                metadata=_parse_json(r.meta_json, {}),
            )
            for r in rows
        ]

    async def get_evidence(self, evidence_id: UUID) -> Optional[Evidence]:
        result = await self.db.execute(
            select(EvidenceORM).where(EvidenceORM.id == str(evidence_id))
        )
        r = result.scalar_one_or_none()
        if not r:
            return None
        from app.domain.enums import EvidenceType

        return Evidence(
            id=UUID(r.id),
            memory_id=UUID(r.memory_id),
            event_id=UUID(r.event_id) if r.event_id else None,
            type=EvidenceType(r.type),
            content=r.content,
            media_path=r.media_path,
            timestamp_ms=r.timestamp_ms,
            confidence=ConfidenceLevel(r.confidence),
            metadata=_parse_json(r.meta_json, {}),
        )

    async def list_evidences_by_partition(self, partition: DataPartition) -> list[Evidence]:
        memories, _ = await self.list_time_memories(partition=partition)
        all_ev = []
        for m in memories:
            all_ev.extend(await self.list_evidences(m.id))
        return all_ev

    async def list_all_work_evidences(self) -> list[Evidence]:
        work_memories, _ = await self.list_time_memories(partition=DataPartition.WORK)
        all_ev = []
        for m in work_memories:
            all_ev.extend(await self.list_evidences(m.id))
        return all_ev

    # --- Events ---
    async def save_event(self, event: Event) -> Event:
        orm = EventORM(
            id=str(event.id),
            memory_id=str(event.memory_id),
            event_type=event.event_type.value,
            start_ms=event.start_ms,
            end_ms=event.end_ms,
            label=event.label,
            confidence=event.confidence.value,
            evidence_ids=json.dumps([str(e) for e in event.evidence_ids]),
            entity_ids=json.dumps([str(e) for e in event.entity_ids]),
        )
        self.db.add(orm)
        await self.db.commit()
        return event

    async def list_events(self, memory_id: UUID) -> list[Event]:
        result = await self.db.execute(
            select(EventORM).where(EventORM.memory_id == str(memory_id))
        )
        rows = result.scalars().all()
        from app.domain.enums import ConfidenceLevel, EventType
        return [
            Event(
                id=UUID(r.id),
                memory_id=UUID(r.memory_id),
                event_type=EventType(r.event_type),
                start_ms=r.start_ms,
                end_ms=r.end_ms,
                label=r.label,
                confidence=ConfidenceLevel(r.confidence),
                evidence_ids=[UUID(e) for e in _parse_json(r.evidence_ids)],
                entity_ids=[UUID(e) for e in _parse_json(r.entity_ids)],
            )
            for r in rows
        ]

    # --- Entities ---
    async def save_entity(self, entity: Entity) -> Entity:
        orm = EntityORM(
            id=str(entity.id),
            entity_type=entity.entity_type,
            name=entity.name,
            partition=entity.partition.value,
            confidence=entity.confidence.value,
            memory_ids=json.dumps([str(m) for m in entity.memory_ids]),
            meta_json=json.dumps(entity.metadata),
        )
        self.db.add(orm)
        await self.db.commit()
        return entity

    def _entity_from_orm(self, r) -> Entity:
        return Entity(
            id=UUID(r.id),
            entity_type=r.entity_type,
            name=r.name,
            partition=DataPartition(r.partition),
            confidence=ConfidenceLevel(r.confidence),
            memory_ids=[UUID(m) for m in _parse_json(r.memory_ids)],
            metadata=_parse_json(r.meta_json, {}),
        )

    async def find_entity(
        self, name: str, entity_type: str, partition: DataPartition
    ) -> Optional[Entity]:
        result = await self.db.execute(
            select(EntityORM).where(
                EntityORM.name == name,
                EntityORM.entity_type == entity_type,
                EntityORM.partition == partition.value,
            )
        )
        r = result.scalar_one_or_none()
        return self._entity_from_orm(r) if r else None

    async def list_entities(
        self, partition: Optional[DataPartition] = None, entity_type: Optional[str] = None
    ) -> list[Entity]:
        query = select(EntityORM)
        if partition:
            query = query.where(EntityORM.partition == partition.value)
        if entity_type:
            query = query.where(EntityORM.entity_type == entity_type)
        result = await self.db.execute(query)
        return [self._entity_from_orm(r) for r in result.scalars().all()]

    async def update_entity(self, entity_id: UUID, **kwargs) -> Optional[Entity]:
        values = {}
        for k, v in kwargs.items():
            if v is None:
                continue
            if k == "memory_ids":
                values[k] = json.dumps([str(m) for m in v])
            elif k == "metadata":
                values[k] = json.dumps(v)
            elif hasattr(v, "value"):
                values[k] = v.value
            else:
                values[k] = v
        if values:
            await self.db.execute(
                update(EntityORM).where(EntityORM.id == str(entity_id)).values(**values)
            )
            await self.db.commit()
        result = await self.db.execute(
            select(EntityORM).where(EntityORM.id == str(entity_id))
        )
        r = result.scalar_one_or_none()
        return self._entity_from_orm(r) if r else None

    # --- Bindings ---
    async def save_binding(self, binding: Binding) -> Binding:
        orm = BindingORM(
            id=str(binding.id),
            binding_type=binding.binding_type.value,
            time_memory_id=str(binding.time_memory_id) if binding.time_memory_id else None,
            space_memory_id=str(binding.space_memory_id) if binding.space_memory_id else None,
            event_id=str(binding.event_id) if binding.event_id else None,
            evidence_id=str(binding.evidence_id) if binding.evidence_id else None,
            anchor_id=str(binding.anchor_id) if binding.anchor_id else None,
            confidence=binding.confidence.value,
            user_confirmed=binding.user_confirmed,
        )
        self.db.add(orm)
        await self.db.commit()
        return binding

    def _binding_from_orm(self, r) -> Binding:
        return Binding(
            id=UUID(r.id),
            binding_type=BindingType(r.binding_type),
            time_memory_id=UUID(r.time_memory_id) if r.time_memory_id else None,
            space_memory_id=UUID(r.space_memory_id) if r.space_memory_id else None,
            event_id=UUID(r.event_id) if r.event_id else None,
            evidence_id=UUID(r.evidence_id) if r.evidence_id else None,
            anchor_id=UUID(r.anchor_id) if r.anchor_id else None,
            confidence=ConfidenceLevel(r.confidence),
            user_confirmed=r.user_confirmed,
        )

    async def get_binding(self, binding_id: UUID) -> Optional[Binding]:
        result = await self.db.execute(
            select(BindingORM).where(BindingORM.id == str(binding_id))
        )
        r = result.scalar_one_or_none()
        return self._binding_from_orm(r) if r else None

    async def list_bindings(
        self,
        time_memory_id: Optional[UUID] = None,
        space_memory_id: Optional[UUID] = None,
    ) -> list[Binding]:
        query = select(BindingORM)
        if time_memory_id:
            query = query.where(BindingORM.time_memory_id == str(time_memory_id))
        if space_memory_id:
            query = query.where(BindingORM.space_memory_id == str(space_memory_id))
        result = await self.db.execute(query)
        return [self._binding_from_orm(r) for r in result.scalars().all()]

    async def update_binding(self, binding_id: UUID, **kwargs) -> Optional[Binding]:
        values = {}
        for k, v in kwargs.items():
            if v is None:
                continue
            if hasattr(v, "value"):
                values[k] = v.value
            else:
                values[k] = v
        if values:
            await self.db.execute(
                update(BindingORM).where(BindingORM.id == str(binding_id)).values(**values)
            )
            await self.db.commit()
        return await self.get_binding(binding_id)

    async def delete_binding(self, binding_id: UUID):
        await self.db.execute(delete(BindingORM).where(BindingORM.id == str(binding_id)))
        await self.db.commit()

    # --- Persons ---
    async def save_person(self, person: Person) -> Person:
        orm = PersonORM(
            id=str(person.id),
            name=person.name,
            role=person.role,
            notes=person.notes,
            partition=person.partition.value,
            memory_ids=json.dumps([str(m) for m in person.memory_ids]),
            confidence=person.confidence.value,
        )
        self.db.add(orm)
        await self.db.commit()
        return person

    async def get_person(self, person_id: UUID) -> Optional[Person]:
        result = await self.db.execute(
            select(PersonORM).where(PersonORM.id == str(person_id))
        )
        orm = result.scalar_one_or_none()
        if not orm:
            return None
        from app.domain.enums import ConfidenceLevel
        return Person(
            id=UUID(orm.id),
            name=orm.name,
            role=orm.role,
            notes=orm.notes,
            partition=DataPartition(orm.partition),
            memory_ids=[UUID(m) for m in _parse_json(orm.memory_ids)],
            confidence=ConfidenceLevel(orm.confidence),
        )

    async def list_persons(self, partition: Optional[DataPartition] = None) -> list[Person]:
        query = select(PersonORM)
        if partition:
            query = query.where(PersonORM.partition == partition.value)
        result = await self.db.execute(query)
        rows = result.scalars().all()
        from app.domain.enums import ConfidenceLevel
        return [
            Person(
                id=UUID(r.id),
                name=r.name,
                role=r.role,
                notes=r.notes,
                partition=DataPartition(r.partition),
                memory_ids=[UUID(m) for m in _parse_json(r.memory_ids)],
                confidence=ConfidenceLevel(r.confidence),
            )
            for r in rows
        ]

    async def update_person(self, person_id: UUID, **kwargs) -> Optional[Person]:
        values = {}
        for k, v in kwargs.items():
            if v is not None:
                if k == "memory_ids":
                    values[k] = json.dumps([str(m) for m in v])
                elif hasattr(v, "value"):
                    values[k] = v.value
                else:
                    values[k] = v
        if values:
            await self.db.execute(
                update(PersonORM).where(PersonORM.id == str(person_id)).values(**values)
            )
            await self.db.commit()
        return await self.get_person(person_id)

    async def delete_person(self, person_id: UUID):
        await self.db.execute(delete(PersonORM).where(PersonORM.id == str(person_id)))
        await self.db.commit()

    # --- Query logs ---
    async def save_query_log(self, query_id: UUID, question: str, scope: str, status: str, answer: Optional[str], result_json: dict):
        orm = QueryLogORM(
            id=str(query_id),
            question=question,
            scope=scope,
            result_status=status,
            answer=answer,
            result_json=json.dumps(result_json),
        )
        self.db.add(orm)
        await self.db.commit()

    async def get_query_log(self, query_id: UUID) -> Optional[dict]:
        result = await self.db.execute(
            select(QueryLogORM).where(QueryLogORM.id == str(query_id))
        )
        orm = result.scalar_one_or_none()
        if not orm:
            return None
        return {
            "query_id": orm.id,
            "question": orm.question,
            "scope": orm.scope,
            "result_status": orm.result_status,
            "answer": orm.answer,
            "result": _parse_json(orm.result_json, {}),
        }
