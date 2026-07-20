from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

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


class Evidence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    memory_id: UUID
    event_id: Optional[UUID] = None
    type: EvidenceType
    content: str = ""
    media_path: Optional[str] = None
    timestamp_ms: int = 0
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    metadata: dict = Field(default_factory=dict)


class Event(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    memory_id: UUID
    event_type: EventType
    start_ms: int = 0
    end_ms: int = 0
    label: str = ""
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    evidence_ids: list[UUID] = Field(default_factory=list)
    entity_ids: list[UUID] = Field(default_factory=list)


class Entity(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    entity_type: str
    name: str
    partition: DataPartition
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    memory_ids: list[UUID] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class Person(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    role: str = ""
    notes: str = ""
    partition: DataPartition
    memory_ids: list[UUID] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH


class Binding(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    binding_type: BindingType
    time_memory_id: Optional[UUID] = None
    space_memory_id: Optional[UUID] = None
    event_id: Optional[UUID] = None
    evidence_id: Optional[UUID] = None
    anchor_id: Optional[UUID] = None
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    user_confirmed: bool = False


class SpaceAnchor(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    space_id: UUID
    name: str
    anchor_type: str = "generic"
    position: dict = Field(default_factory=lambda: {"x": 0, "y": 0, "z": 0})
    evidence_ids: list[UUID] = Field(default_factory=list)
    related_memory_ids: list[UUID] = Field(default_factory=list)
    notes: str = ""


class NavigationSummary(BaseModel):
    persons: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    spaces: list[str] = Field(default_factory=list)
    key_moments: list[dict] = Field(default_factory=list)
    evidence_entries: list[dict] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)


class TimeMemory(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str = ""
    scene: TimeScene
    partition: DataPartition
    status: MemoryStatus = MemoryStatus.NOT_STARTED
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: int = 0
    identify_brief: str = ""
    navigation_summary: Optional[NavigationSummary] = None
    key_frames: list[dict] = Field(default_factory=list)
    evidence_status: str = "pending"
    is_favorited: bool = False
    is_locked: bool = False
    user_note: str = ""
    session_id: Optional[UUID] = None


class SpaceMemory(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str = ""
    partition: DataPartition = DataPartition.WORK
    status: MemoryStatus = MemoryStatus.NOT_STARTED
    quality: Optional[SpaceQuality] = None
    model_url: Optional[str] = None
    anchors: list[SpaceAnchor] = Field(default_factory=list)
    captured_at: Optional[datetime] = None
    identify_brief: str = ""
    scene_summary: Optional[str] = None
    model_format: Optional[str] = None
    loop_angle: Optional[float] = None
    is_favorited: bool = False
    session_id: Optional[UUID] = None
    scene_type: Optional[str] = None
    poses_url: Optional[str] = None
    poses_sha256: Optional[str] = None
    pose_count: Optional[int] = None
    anchor_url: Optional[str] = None
    anchor_sha256: Optional[str] = None
    anchor_method: Optional[str] = None
    recording_duration_sec: float = 0.0
    anchor_position_x: float = 0.0
    anchor_position_y: float = 0.0
    anchor_position_z: float = 0.0


class IngestSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    memory_type: MemoryType
    scene: Optional[TimeScene] = None
    partition: DataPartition = DataPartition.WORK
    status: MemoryStatus = MemoryStatus.RECORDING
    memory_id: Optional[UUID] = None
    title: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    frame_count: int = 0
    audio_chunk_count: int = 0
    video_path: Optional[str] = None


class ImuSample(BaseModel):
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float
    timestamp_ms: int
