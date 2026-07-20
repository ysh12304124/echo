from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer

from app.domain.enums import (
    ConfidenceLevel,
    DataPartition,
    EvidenceType,
    MemoryStatus,
    MemoryType,
    QueryResultStatus,
    QueryScope,
    SpaceQuality,
    TimeScene,
)
from app.domain.models import NavigationSummary


BEIJING_TZ = timezone(timedelta(hours=8))


def format_beijing_time(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


# --- Ingest ---

class CreateSessionRequest(BaseModel):
    memory_type: MemoryType
    scene: Optional[TimeScene] = None
    partition: DataPartition = DataPartition.WORK
    title: str = ""


class IngestSessionResponse(BaseModel):
    session_id: UUID
    memory_type: MemoryType
    scene: Optional[TimeScene] = None
    partition: DataPartition
    status: MemoryStatus
    created_at: datetime

    @field_serializer("created_at")
    def _format_created_at(self, value: datetime) -> Optional[str]:
        # DB stores UTC; API displays Beijing time to match backend logs.
        return format_beijing_time(value)


class UploadAckResponse(BaseModel):
    id: UUID
    accepted: bool
    filtered: bool = False
    filename: Optional[str] = None
    media_url: Optional[str] = None


class ImuSampleRequest(BaseModel):
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float
    timestamp_ms: int


class ImuBatchRequest(BaseModel):
    samples: list[ImuSampleRequest] = Field(default_factory=list)


class ImuBatchResponse(BaseModel):
    session_id: UUID
    accepted_count: int


class MemorySummaryResponse(BaseModel):
    memory_id: UUID
    memory_type: MemoryType
    status: MemoryStatus
    identify_brief: str = ""
    title: str = ""
    scene: Optional[TimeScene] = None
    partition: Optional[DataPartition] = None
    started_at: Optional[datetime] = None
    duration_seconds: int = 0
    evidence_status: str = "pending"
    is_favorited: bool = False

    @field_serializer("started_at")
    def _format_started_at(self, value: Optional[datetime]) -> Optional[str]:
        # DB stores UTC; API displays Beijing time to match backend logs.
        return format_beijing_time(value)


class MemoryListResponse(BaseModel):
    items: list[MemorySummaryResponse]
    total: int


class UpdateMemoryRequest(BaseModel):
    title: Optional[str] = None
    is_favorited: Optional[bool] = None
    is_locked: Optional[bool] = None
    user_note: Optional[str] = None


class TimeMemoryDetailResponse(BaseModel):
    memory_id: UUID
    title: str
    scene: TimeScene
    partition: DataPartition
    status: MemoryStatus
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: int = 0
    identify_brief: str = ""
    navigation_summary: Optional[NavigationSummary] = None
    evidence_status: str = "pending"
    is_favorited: bool = False
    is_locked: bool = False
    key_frames: list = []

    @field_serializer("started_at", "ended_at")
    def _format_time_fields(self, value: Optional[datetime]) -> Optional[str]:
        # DB stores UTC; API displays Beijing time to match backend logs.
        return format_beijing_time(value)


class AnchorResponse(BaseModel):
    position: dict = Field(default_factory=dict)
    method: Optional[str] = None


class SpaceAnchorResponse(BaseModel):
    anchor_id: UUID
    name: str
    anchor_type: str
    position: dict


class SpaceMemoryDetailResponse(BaseModel):
    space_id: UUID
    title: str
    partition: DataPartition
    status: MemoryStatus
    quality: Optional[SpaceQuality] = None
    model_url: Optional[str] = None
    anchors: list[SpaceAnchorResponse] = Field(default_factory=list)
    captured_at: Optional[datetime] = None
    is_favorited: bool = False
    identify_brief: str = ""
    scene_summary: Optional[str] = None
    model_format: Optional[str] = None
    loop_angle: Optional[float] = None
    scene_type: Optional[str] = None
    poses_url: Optional[str] = None
    anchor: Optional[AnchorResponse] = None
    recording_duration_sec: float = 0.0

    @field_serializer("captured_at")
    def _format_captured_at(self, value: Optional[datetime]) -> Optional[str]:
        # DB stores UTC; API displays Beijing time to match backend logs.
        return format_beijing_time(value)


class SpaceListResponse(BaseModel):
    items: list[SpaceMemoryDetailResponse]
    total: int


# --- Query ---

class QueryRequest(BaseModel):
    question: str
    scope: QueryScope
    memory_id: Optional[UUID] = None
    space_id: Optional[UUID] = None


class QueryEvidenceResponse(BaseModel):
    evidence_id: UUID
    type: EvidenceType
    content: str
    confidence: ConfidenceLevel
    media_url: Optional[str] = None
    timestamp_ms: int = 0


class QuerySourceResponse(BaseModel):
    memory_id: UUID
    memory_title: str
    scene: Optional[TimeScene] = None
    time_offset_seconds: int = 0


class QueryResponse(BaseModel):
    query_id: UUID
    status: QueryResultStatus
    answer: Optional[str] = None
    evidences: list[QueryEvidenceResponse] = Field(default_factory=list)
    sources: list[QuerySourceResponse] = Field(default_factory=list)
    uncertainty_reason: Optional[str] = None


class VoiceTranscriptionResponse(BaseModel):
    transcript: str = ""
    duration_ms: int = 0
    asr_avg_logprob: Optional[float] = None
    asr_accepted: bool
    rejection_reason: Optional[str] = None


class VoiceQueryResponse(BaseModel):
    transcript: str = ""
    duration_ms: int = 0
    asr_avg_logprob: Optional[float] = None
    asr_accepted: bool
    rejection_reason: Optional[str] = None
    result: Optional[QueryResponse] = None


# --- Persons ---

class PersonSummaryResponse(BaseModel):
    person_id: UUID
    name: str
    role: str = ""
    memory_count: int = 0


class PersonListResponse(BaseModel):
    items: list[PersonSummaryResponse]
    total: int


class PersonDetailResponse(BaseModel):
    person_id: UUID
    name: str
    role: str = ""
    notes: str = ""
    related_memories: list[UUID] = Field(default_factory=list)


class UpdatePersonRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    notes: Optional[str] = None
    merge_with_id: Optional[UUID] = None


class SplitPersonRequest(BaseModel):
    memory_ids: list[UUID]
    new_name: str = ""


# --- Entities ---

class EntitySummaryResponse(BaseModel):
    entity_id: UUID
    name: str
    entity_type: str
    confidence: ConfidenceLevel
    memory_count: int = 0


class EntityListResponse(BaseModel):
    items: list[EntitySummaryResponse]
    total: int


# --- Bindings ---

class BindingResponse(BaseModel):
    binding_id: UUID
    binding_type: str
    time_memory_id: Optional[UUID] = None
    space_memory_id: Optional[UUID] = None
    confidence: ConfidenceLevel
    user_confirmed: bool = False


class BindingListResponse(BaseModel):
    items: list[BindingResponse]
    total: int


# --- Space update ---

class UpdateSpaceRequest(BaseModel):
    title: Optional[str] = None
    is_favorited: Optional[bool] = None


class ExportResultResponse(BaseModel):
    export_id: UUID
    content: dict


# --- 算力服务回调 (docs/protocols/compute-service.md) ---

class ComputeCallbackRequest(BaseModel):
    job_id: str
    memory_id: UUID
    status: str = "succeeded"  # succeeded | failed
    result: dict = Field(default_factory=dict)
    error: Optional[str] = None


class ComputeCallbackAck(BaseModel):
    accepted: bool = True
