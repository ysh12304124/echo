import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.providers import get_settings


class Base(DeclarativeBase):
    pass


class SessionORM(Base):
    __tablename__ = "ingest_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(20))
    scene: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    partition: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    memory_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    audio_chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    frame_paths: Mapped[str] = mapped_column(Text, default="[]")
    audio_paths: Mapped[str] = mapped_column(Text, default="[]")


class TimeMemoryORM(Base):
    __tablename__ = "time_memories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    scene: Mapped[str] = mapped_column(String(20))
    partition: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    identify_brief: Mapped[str] = mapped_column(String(500), default="")
    navigation_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_status: Mapped[str] = mapped_column(String(50), default="pending")
    is_favorited: Mapped[bool] = mapped_column(Boolean, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    user_note: Mapped[str] = mapped_column(Text, default="")
    session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class SpaceMemoryORM(Base):
    __tablename__ = "space_memories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    partition: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    quality: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    model_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    anchors: Mapped[str] = mapped_column(Text, default="[]")
    captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    identify_brief: Mapped[str] = mapped_column(String(500), default="")
    is_favorited: Mapped[bool] = mapped_column(Boolean, default=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class EvidenceORM(Base):
    __tablename__ = "evidences"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(String(36), index=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    type: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    media_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    timestamp_ms: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[str] = mapped_column(String(10), default="high")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")


class EventORM(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    start_ms: Mapped[int] = mapped_column(Integer, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(200), default="")
    confidence: Mapped[str] = mapped_column(String(10), default="high")
    evidence_ids: Mapped[str] = mapped_column(Text, default="[]")
    entity_ids: Mapped[str] = mapped_column(Text, default="[]")


class PersonORM(Base):
    __tablename__ = "persons"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    partition: Mapped[str] = mapped_column(String(20))
    memory_ids: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[str] = mapped_column(String(10), default="high")


class EntityORM(Base):
    __tablename__ = "entities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    partition: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[str] = mapped_column(String(10), default="high")
    memory_ids: Mapped[str] = mapped_column(Text, default="[]")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")


class BindingORM(Base):
    __tablename__ = "bindings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    binding_type: Mapped[str] = mapped_column(String(20))
    time_memory_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    space_memory_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    evidence_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    anchor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    confidence: Mapped[str] = mapped_column(String(10), default="high")
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class QueryLogORM(Base):
    __tablename__ = "query_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(20))
    result_status: Mapped[str] = mapped_column(String(20))
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    from pathlib import Path
    Path("./data").mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
