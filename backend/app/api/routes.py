from __future__ import annotations

import json
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import BindingType, DataPartition, MemoryStatus, MemoryType, TimeScene
from app.domain.models import ImuSample, NavigationSummary, SpaceMemory, TimeMemory
from app.providers import get_provider_factory, get_settings
from app.repositories.database import get_db
from app.repositories.memory_repo import MemoryRepository
from app.schemas import (
    AnchorResponse,
    BindingListResponse,
    BindingResponse,
    ComputeCallbackAck,
    ComputeCallbackRequest,
    CreateSessionRequest,
    EntityListResponse,
    EntitySummaryResponse,
    ExportResultResponse,
    IngestSessionResponse,
    ImuBatchRequest,
    ImuBatchResponse,
    MemoryListResponse,
    MemorySummaryResponse,
    PersonDetailResponse,
    PersonListResponse,
    PersonSummaryResponse,
    QueryRequest,
    QueryResponse,
    SpaceListResponse,
    SpaceMemoryDetailResponse,
    SpaceAnchorResponse,
    SplitPersonRequest,
    TimeMemoryDetailResponse,
    UpdateMemoryRequest,
    UpdatePersonRequest,
    UpdateSpaceRequest,
    UploadAckResponse,
)
from app.logging_setup import get_logger
from app.services.compute_client import apply_audio_result, apply_space_result, apply_time_result
from app.services.ingest_pipeline import IngestPipeline
from app.services.person_service import PersonService
from app.services.query_engine import QueryEngine


class ExportQueryRequest(BaseModel):
    query_id: UUID

router = APIRouter()
log = get_logger("api")


def get_repo(db: AsyncSession = Depends(get_db)) -> MemoryRepository:
    return MemoryRepository(db)


def _navigation_summary_response(memory) -> Optional[NavigationSummary]:
    if not memory.navigation_summary and not memory.key_frames:
        return None
    nav = memory.navigation_summary or NavigationSummary()
    key_moments = []
    for index, frame in enumerate(memory.key_frames, start=1):
        media_path = frame.get("media_path") or ""
        if not media_path:
            continue
        media_url = f"/api/v1/media/{media_path}"
        timestamp_ms = int(frame.get("timestamp_ms") or 0)
        label = frame.get("label") or ""
        description = frame.get("description") or label
        key_moments.append(
            {
                "id": f"frame-{index}",
                "label": label,
                "description": description,
                "time_offset_seconds": timestamp_ms // 1000,
                "image_url": media_url,
                "type": "visual",
                "confidence": "high",
            }
        )

    if key_moments:
        nav.key_moments = key_moments
    return nav


# --- Ingest ---

@router.post("/ingest/sessions", response_model=IngestSessionResponse, status_code=201)
async def create_session(req: CreateSessionRequest, repo: MemoryRepository = Depends(get_repo)):
    pipeline = IngestPipeline(repo)
    try:
        session = await pipeline.create_session(
            memory_type=req.memory_type,
            scene=req.scene,
            partition=req.partition,
            title=req.title,
        )
    except ValueError as e:
        log.warning("创建会话失败: %s", e)
        raise HTTPException(400, str(e))
    log.info(
        "会话已创建 session=%s type=%s scene=%s partition=%s title=%r",
        session.id,
        session.memory_type.value,
        session.scene.value if session.scene else "-",
        session.partition.value,
        req.title,
    )
    return IngestSessionResponse(
        session_id=session.id,
        memory_type=session.memory_type,
        scene=session.scene,
        partition=session.partition,
        status=session.status,
        created_at=session.created_at,
    )


@router.post("/ingest/sessions/{session_id}/video", response_model=UploadAckResponse, status_code=201)
async def upload_video_chunk(
    session_id: UUID,
    file: UploadFile = File(...),
    index: int = Form(...),
    is_last: bool = Form(False),
    filename: Optional[str] = Form(None),
    repo: MemoryRepository = Depends(get_repo),
):
    """眼镜边录边发、手机不落地转发的视频分片；按到达顺序 append 到会话视频文件。"""
    pipeline = IngestPipeline(repo)
    data = await file.read()
    try:
        video_path = await pipeline.append_video_chunk(session_id, index, is_last, filename, data)
    except ValueError as e:
        log.warning("视频分片上传失败 session=%s: %s", session_id, e)
        raise HTTPException(404, str(e))
    log.info(
        "收到视频分片 session=%s index=%d bytes=%d is_last=%s filename=%s",
        session_id, index, len(data), is_last, filename,
    )
    media_url = f"/api/v1/media/sessions/{session_id}/video/{filename}" if (video_path and filename) else None
    return UploadAckResponse(
        id=session_id,
        accepted=True,
        filtered=False,
        filename=filename if is_last else None,
        media_url=media_url,
    )


@router.post("/ingest/sessions/{session_id}/video/patch", response_model=UploadAckResponse, status_code=201)
async def patch_video_header(
    session_id: UUID,
    file: UploadFile = File(...),
    offset: int = Form(...),
    repo: MemoryRepository = Depends(get_repo),
):
    """覆盖写视频临时文件头部：MediaRecorder 结束时会回改 mdat box 等头部字段，
    边录边发已发出的旧值需要在 video_end 之前用录制结束后重读的最终头部覆盖。"""
    pipeline = IngestPipeline(repo)
    data = await file.read()
    try:
        await pipeline.patch_video_header(session_id, offset, data)
    except ValueError as e:
        log.warning("视频头部覆盖失败 session=%s: %s", session_id, e)
        raise HTTPException(404, str(e))
    return UploadAckResponse(id=session_id, accepted=True, filtered=False)


@router.post("/ingest/sessions/{session_id}/audio", response_model=UploadAckResponse, status_code=201)
async def upload_audio(
    session_id: UUID,
    file: UploadFile = File(...),
    timestamp_ms: int = Form(...),
    repo: MemoryRepository = Depends(get_repo),
):
    pipeline = IngestPipeline(repo)
    data = await file.read()
    try:
        audio_id = await pipeline.upload_audio(session_id, data, timestamp_ms)
    except ValueError as e:
        log.warning("语音上传失败 session=%s: %s", session_id, e)
        raise HTTPException(404, str(e))
    log.info(
        "收到语音 session=%s bytes=%d ts=%d",
        session_id,
        len(data),
        timestamp_ms,
    )
    return UploadAckResponse(id=audio_id, accepted=True, filtered=False)


@router.post("/ingest/sessions/{session_id}/complete", response_model=MemorySummaryResponse)
async def complete_session(
    session_id: UUID,
    repo: MemoryRepository = Depends(get_repo),
):
    pipeline = IngestPipeline(repo)
    log.info("会话结束，开始处理 session=%s", session_id)
    try:
        memory = await pipeline.complete_session(session_id)
    except ValueError as e:
        log.warning("会话处理失败 session=%s: %s", session_id, e)
        raise HTTPException(404, str(e))
    log.info(
        "记忆已生成 session=%s memory=%s type=%s status=%s brief=%r",
        session_id,
        memory.id,
        "space" if isinstance(memory, SpaceMemory) else "time",
        memory.status.value,
        memory.identify_brief,
    )

    if isinstance(memory, SpaceMemory):
        return MemorySummaryResponse(
            memory_id=memory.id,
            memory_type=MemoryType.SPACE,
            status=memory.status,
            identify_brief=memory.identify_brief,
            title=memory.title,
        )
    return MemorySummaryResponse(
        memory_id=memory.id,
        memory_type=MemoryType.TIME,
        status=memory.status,
        identify_brief=memory.identify_brief,
        title=memory.title,
        scene=memory.scene,
        partition=memory.partition,
    )


@router.post(
    "/ingest/sessions/{session_id}/imu",
    response_model=ImuBatchResponse,
    status_code=201,
)
async def upload_imu(
    session_id: UUID,
    req: ImuBatchRequest,
    repo: MemoryRepository = Depends(get_repo),
):
    # 空间记忆现附加到当前场景 session 下（双指双击触控板开关），不再要求独立的 SPACE 会话。
    pipeline = IngestPipeline(repo)
    samples = [ImuSample(**sample.model_dump()) for sample in req.samples]
    try:
        accepted_count = await pipeline.append_imu_samples(session_id, samples)
    except ValueError as e:
        raise HTTPException(404, str(e))
    log.info("收到 IMU 批数据 session=%s count=%d", session_id, accepted_count)
    return ImuBatchResponse(session_id=session_id, accepted_count=accepted_count)


# --- 算力服务回调 (docs/protocols/compute-service.md) ---
# 本期简化：只用共享密钥头校验，不做来源 IP 限制/签名/重试（详见协议文档"简化"一节）。

def _check_internal_token(x_internal_token: Optional[str]) -> None:
    settings = get_settings()
    if x_internal_token != settings.internal_token:
        raise HTTPException(401, "Invalid internal token")


@router.post("/internal/callback/audio", response_model=ComputeCallbackAck)
async def internal_callback_audio(
    req: ComputeCallbackRequest,
    x_internal_token: Optional[str] = Header(default=None),
    repo: MemoryRepository = Depends(get_repo),
):
    _check_internal_token(x_internal_token)
    log.info(
        "收到算力回调(audio) job=%s memory=%s status=%s", req.job_id, req.memory_id, req.status
    )
    await apply_audio_result(repo, req.memory_id, req.status, req.result)
    return ComputeCallbackAck(accepted=True)


@router.post("/internal/callback/time", response_model=ComputeCallbackAck)
async def internal_callback_time(
    req: ComputeCallbackRequest,
    x_internal_token: Optional[str] = Header(default=None),
    repo: MemoryRepository = Depends(get_repo),
):
    _check_internal_token(x_internal_token)
    log.info(
        "收到算力回调(time) job=%s memory=%s status=%s", req.job_id, req.memory_id, req.status
    )
    await apply_time_result(repo, req.memory_id, req.status, req.result)
    return ComputeCallbackAck(accepted=True)


@router.post("/internal/callback/space", response_model=ComputeCallbackAck)
async def internal_callback_space(
    req: ComputeCallbackRequest,
    x_internal_token: Optional[str] = Header(default=None),
    repo: MemoryRepository = Depends(get_repo),
):
    _check_internal_token(x_internal_token)
    log.info(
        "收到算力回调(space) job=%s memory=%s status=%s", req.job_id, req.memory_id, req.status
    )
    await apply_space_result(repo, req.memory_id, req.status, req.result)
    return ComputeCallbackAck(accepted=True)


# --- Memories ---

@router.get("/memories", response_model=MemoryListResponse)
async def list_memories(
    partition: Optional[DataPartition] = None,
    scene: Optional[TimeScene] = None,
    status: Optional[MemoryStatus] = None,
    limit: int = 20,
    offset: int = 0,
    repo: MemoryRepository = Depends(get_repo),
):
    memories, total = await repo.list_time_memories(partition, scene, status, limit, offset)
    items = [
        MemorySummaryResponse(
            memory_id=m.id,
            memory_type=MemoryType.TIME,
            status=m.status,
            identify_brief=m.identify_brief,
            title=m.title,
            scene=m.scene,
            partition=m.partition,
            started_at=m.started_at,
            duration_seconds=m.duration_seconds,
            evidence_status=m.evidence_status,
            is_favorited=m.is_favorited,
        )
        for m in memories
    ]
    resp = MemoryListResponse(items=items, total=total)
    log.info(
        "查询记忆列表 partition=%s scene=%s status=%s limit=%d offset=%d -> total=%d 返回=%d 结果=%s",
        partition, scene, status, limit, offset, total, len(items),
        json.dumps(resp.model_dump(mode="json"), ensure_ascii=False),
    )
    return resp


@router.get("/memories/{memory_id}", response_model=TimeMemoryDetailResponse)
async def get_memory(memory_id: UUID, repo: MemoryRepository = Depends(get_repo)):
    memory = await repo.get_time_memory(memory_id)
    if not memory:
        raise HTTPException(404, "Memory not found")
    return TimeMemoryDetailResponse(
        memory_id=memory.id,
        title=memory.title,
        scene=memory.scene,
        partition=memory.partition,
        status=memory.status,
        started_at=memory.started_at,
        ended_at=memory.ended_at,
        duration_seconds=memory.duration_seconds,
        identify_brief=memory.identify_brief,
        navigation_summary=_navigation_summary_response(memory),
        evidence_status=memory.evidence_status,
        is_favorited=memory.is_favorited,
        is_locked=memory.is_locked,
        key_frames=_format_key_frames(memory.key_frames or []),
    )


@router.patch("/memories/{memory_id}", response_model=TimeMemoryDetailResponse)
async def update_memory(
    memory_id: UUID,
    req: UpdateMemoryRequest,
    repo: MemoryRepository = Depends(get_repo),
):
    updates = req.model_dump(exclude_unset=True)
    memory = await repo.update_time_memory(memory_id, **updates)
    if not memory:
        raise HTTPException(404, "Memory not found")
    return await get_memory(memory_id, repo)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: UUID, repo: MemoryRepository = Depends(get_repo)):
    memory = await repo.get_time_memory(memory_id)
    if not memory:
        raise HTTPException(404, "Memory not found")
    if memory.is_locked:
        raise HTTPException(400, "记忆已锁定，无法删除")
    # 级联：删除关联证据的媒体文件与向量索引。
    factory = get_provider_factory()
    blob = factory.blob_store()
    vector = factory.vector_store()
    for ev in await repo.list_evidences(memory_id):
        if ev.media_path:
            key = ev.media_path.split("/blobs/", 1)[-1]
            await blob.delete(key)
    try:
        await vector.delete_by_filter({"memory_id": str(memory_id)})
    except NotImplementedError:
        pass
    await repo.delete_time_memory(memory_id)


# --- Spaces ---

@router.get("/spaces", response_model=SpaceListResponse)
async def list_spaces(
    partition: Optional[DataPartition] = None,
    repo: MemoryRepository = Depends(get_repo),
):
    spaces, total = await repo.list_space_memories(partition)
    items = [
        SpaceMemoryDetailResponse(
            space_id=s.id,
            title=s.title,
            partition=s.partition,
            status=s.status,
            quality=s.quality,
            model_url=s.model_url,
            anchors=[
                SpaceAnchorResponse(
                    anchor_id=a.id,
                    name=a.name,
                    anchor_type=a.anchor_type,
                    position=a.position,
                )
                for a in s.anchors
            ],
            captured_at=s.captured_at,
            is_favorited=s.is_favorited,
            identify_brief=s.identify_brief,
            scene_summary=s.scene_summary,
            model_format=s.model_format,
            loop_angle=s.loop_angle,
            scene_type=s.scene_type,
            poses_url=s.poses_url,
            anchor=AnchorResponse(position={"x": s.anchor_position_x, "y": s.anchor_position_y, "z": s.anchor_position_z}, method=s.anchor_method) if s.anchor_method else None,
            recording_duration_sec=s.recording_duration_sec,
        )
        for s in spaces
    ]
    return SpaceListResponse(items=items, total=total)


@router.get("/spaces/{space_id}", response_model=SpaceMemoryDetailResponse)
async def get_space(space_id: UUID, repo: MemoryRepository = Depends(get_repo)):
    space = await repo.get_space_memory(space_id)
    if not space:
        raise HTTPException(404, "Space not found")
    return SpaceMemoryDetailResponse(
        space_id=space.id,
        title=space.title,
        partition=space.partition,
        status=space.status,
        quality=space.quality,
        model_url=space.model_url,
        anchors=[
            SpaceAnchorResponse(
                anchor_id=a.id,
                name=a.name,
                anchor_type=a.anchor_type,
                position=a.position,
            )
            for a in space.anchors
        ],
        captured_at=space.captured_at,
        is_favorited=space.is_favorited,
        identify_brief=space.identify_brief,
        scene_summary=space.scene_summary,
        model_format=space.model_format,
        loop_angle=space.loop_angle,
        scene_type=space.scene_type,
        poses_url=space.poses_url,
        anchor=AnchorResponse(position={"x": space.anchor_position_x, "y": space.anchor_position_y, "z": space.anchor_position_z}, method=space.anchor_method) if space.anchor_method else None,
        recording_duration_sec=space.recording_duration_sec,
    )


@router.patch("/spaces/{space_id}", response_model=SpaceMemoryDetailResponse)
async def update_space(
    space_id: UUID,
    req: UpdateSpaceRequest,
    repo: MemoryRepository = Depends(get_repo),
):
    space = await repo.get_space_memory(space_id)
    if not space:
        raise HTTPException(404, "Space not found")
    await repo.update_space_memory(space_id, **req.model_dump(exclude_unset=True))
    return await get_space(space_id, repo)


@router.delete("/spaces/{space_id}", status_code=204)
async def delete_space(space_id: UUID, repo: MemoryRepository = Depends(get_repo)):
    space = await repo.get_space_memory(space_id)
    if not space:
        raise HTTPException(404, "Space not found")
    factory = get_provider_factory()
    blob = factory.blob_store()
    if space.model_url:
        key = space.model_url.split("/media/", 1)[-1]
        await blob.delete(key)
        model_dir = key.rsplit("/", 1)[0]
        await blob.delete(model_dir + "/poses.txt")
        await blob.delete(model_dir + "/anchor.json")
    await repo.delete_space_memory(space_id)


# --- Time-Space Bindings ---

@router.get("/memories/{memory_id}/bindings", response_model=BindingListResponse)
async def list_memory_bindings(memory_id: UUID, repo: MemoryRepository = Depends(get_repo)):
    bindings = await repo.list_bindings(time_memory_id=memory_id)
    items = [
        BindingResponse(
            binding_id=b.id,
            binding_type=b.binding_type.value,
            time_memory_id=b.time_memory_id,
            space_memory_id=b.space_memory_id,
            confidence=b.confidence,
            user_confirmed=b.user_confirmed,
        )
        for b in bindings
    ]
    return BindingListResponse(items=items, total=len(items))


@router.post("/bindings/{binding_id}/confirm", response_model=BindingResponse)
async def confirm_binding(binding_id: UUID, repo: MemoryRepository = Depends(get_repo)):
    binding = await repo.get_binding(binding_id)
    if not binding:
        raise HTTPException(404, "Binding not found")
    updated = await repo.update_binding(
        binding_id, binding_type=BindingType.MEMORY_LEVEL, user_confirmed=True
    )
    return BindingResponse(
        binding_id=updated.id,
        binding_type=updated.binding_type.value,
        time_memory_id=updated.time_memory_id,
        space_memory_id=updated.space_memory_id,
        confidence=updated.confidence,
        user_confirmed=updated.user_confirmed,
    )


@router.post("/bindings/{binding_id}/reject", status_code=204)
async def reject_binding(binding_id: UUID, repo: MemoryRepository = Depends(get_repo)):
    binding = await repo.get_binding(binding_id)
    if not binding:
        raise HTTPException(404, "Binding not found")
    await repo.delete_binding(binding_id)


# --- Entities ---

@router.get("/entities", response_model=EntityListResponse)
async def list_entities(
    partition: Optional[DataPartition] = None,
    entity_type: Optional[str] = None,
    repo: MemoryRepository = Depends(get_repo),
):
    entities = await repo.list_entities(partition, entity_type)
    items = [
        EntitySummaryResponse(
            entity_id=e.id,
            name=e.name,
            entity_type=e.entity_type,
            confidence=e.confidence,
            memory_count=len(e.memory_ids),
        )
        for e in entities
    ]
    return EntityListResponse(items=items, total=len(items))


# --- Media ---

@router.get("/media/{key:path}")
async def get_media(key: str):
    blob = get_provider_factory().blob_store()
    path = await blob.get_path(key)
    if not path:
        raise HTTPException(404, "Media not found")
    return FileResponse(path)


# --- Query ---

@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest, repo: MemoryRepository = Depends(get_repo)):
    engine = QueryEngine(repo)
    log.info("查询请求 scope=%s q=%r", req.scope.value, req.question)
    result = await engine.query(req.question, req.scope, req.memory_id, req.space_id)
    log.info(
        "查询返回 query=%s status=%s evidences=%d answer=%r",
        result.query_id,
        result.status.value,
        len(result.evidences),
        (result.answer or "")[:80],
    )
    return result


# --- Persons ---

@router.get("/persons", response_model=PersonListResponse)
async def list_persons(
    partition: Optional[DataPartition] = None,
    repo: MemoryRepository = Depends(get_repo),
):
    service = PersonService(repo)
    persons = await service.list_persons(partition)
    items = [
        PersonSummaryResponse(
            person_id=p.id,
            name=p.name,
            role=p.role,
            memory_count=len(p.memory_ids),
        )
        for p in persons
    ]
    return PersonListResponse(items=items, total=len(items))


@router.get("/persons/{person_id}", response_model=PersonDetailResponse)
async def get_person(person_id: UUID, repo: MemoryRepository = Depends(get_repo)):
    service = PersonService(repo)
    person = await service.get_person(person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    return PersonDetailResponse(
        person_id=person.id,
        name=person.name,
        role=person.role,
        notes=person.notes,
        related_memories=person.memory_ids,
    )


@router.patch("/persons/{person_id}", response_model=PersonDetailResponse)
async def update_person(
    person_id: UUID,
    req: UpdatePersonRequest,
    repo: MemoryRepository = Depends(get_repo),
):
    service = PersonService(repo)
    try:
        person = await service.update_person(
            person_id,
            name=req.name,
            role=req.role,
            notes=req.notes,
            merge_with_id=req.merge_with_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not person:
        raise HTTPException(404, "Person not found")
    return await get_person(person.id, repo)


@router.post("/persons/{person_id}/split", response_model=PersonDetailResponse)
async def split_person(
    person_id: UUID,
    req: SplitPersonRequest,
    repo: MemoryRepository = Depends(get_repo),
):
    service = PersonService(repo)
    try:
        new_person = await service.split_person(person_id, req.memory_ids, req.new_name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not new_person:
        raise HTTPException(404, "Person not found")
    return PersonDetailResponse(
        person_id=new_person.id,
        name=new_person.name,
        role=new_person.role,
        notes=new_person.notes,
        related_memories=new_person.memory_ids,
    )


@router.delete("/persons/{person_id}", status_code=204)
async def delete_person_route(person_id: UUID, repo: MemoryRepository = Depends(get_repo)):
    service = PersonService(repo)
    if not await service.delete_person(person_id):
        raise HTTPException(404, "Person not found")


# --- Export ---

@router.post("/export/query-result", response_model=ExportResultResponse)
async def export_query_result(
    req: ExportQueryRequest,
    repo: MemoryRepository = Depends(get_repo),
):
    log = await repo.get_query_log(req.query_id)
    if not log:
        raise HTTPException(404, "Query not found")
    from uuid import uuid4
    return ExportResultResponse(export_id=uuid4(), content=log)

def _format_key_frames(raw: list) -> list:
    result = []
    for kf in raw:
        mp = kf.get('media_path', '')
        if mp.startswith('sessions/'):
            parts = mp.split('/')  # ['sessions','{id}','frames','{name}']
            if len(parts) >= 4:
                kf['media_url'] = f'/api/v1/ingest/sessions/{parts[1]}/frames/{parts[3]}'
        result.append(kf)
    return result
