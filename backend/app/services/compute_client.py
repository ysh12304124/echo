"""后台 -> 算力服务的提交客户端，以及算力回调结果落库的共享处理逻辑。

契约详见 docs/protocols/compute-service.md。设计要点：

- `ComputeClient` 只负责“提交”（异步、发完即走，不等结果）。真正处理完成后的落库，
  由 `apply_audio_result` / `apply_time_result` / `apply_space_result` 完成——这几个函数
  既被 `/internal/callback/*` 路由（收到真实 HTTP 回调时）调用，也被 `MockComputeClient`
  （本地直接回填假结果、跳过网络）在自己开的一个新 DB 会话里直接调用，两条路径复用同一份
  入库逻辑，保证行为一致。
- `MockComputeClient` 是默认模式（`compute_provider_mode=mock`），不依赖真实算力服务，
  离线开发/测试都不会发出网络请求；只有显式配置 `compute_provider_mode=http` 才会真的
  POST 给 `compute_base_url`。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache
import os
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

import httpx

from app.domain.enums import ConfidenceLevel, DataPartition, EvidenceType, MemoryStatus, SpaceQuality
from app.domain.models import Evidence, NavigationSummary
from app.logging_setup import get_logger
from app.providers import ProviderFactory, get_provider_factory, get_settings
from app.repositories.database import async_session_factory
from app.repositories.memory_repo import MemoryRepository

log = get_logger("compute_client")

_SUBMIT_TIMEOUT_SECONDS = 5.0
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _runtime_path(env_name: str, relative: str) -> str:
    return os.getenv(env_name) or str((_REPO_ROOT / relative).resolve())


@dataclass
class AudioAnalyzeJob:
    memory_id: UUID
    session_id: UUID
    partition: DataPartition
    audio_paths: list[str]
    job_id: str = field(default_factory=lambda: f"job-{uuid4()}")


@dataclass
class TimeAnalyzeJob:
    memory_id: UUID
    session_id: UUID
    partition: DataPartition
    video_path: Optional[str]
    audio_paths: list[str]
    models_root: str = field(
        default_factory=lambda: _runtime_path(
            "TIME_MEMORY_MODELS_ROOT", "compute/models/speaker-fusion"
        )
    )
    lrasd_root: str = field(
        default_factory=lambda: _runtime_path(
            "TIME_MEMORY_LRASD_ROOT", "compute/models/speaker-fusion/LR-ASD"
        )
    )
    output_root: str = field(
        default_factory=lambda: _runtime_path(
            "TIME_MEMORY_OUTPUT_ROOT", "backend/data/blobs/time-memory"
        )
    )
    job_id: str = field(default_factory=lambda: f"job-{uuid4()}")


@dataclass
class SpaceAnalyzeJob:
    memory_id: UUID
    session_id: UUID
    partition: DataPartition
    video_path: Optional[str]
    imu_path: Optional[str]
    scene_type: Optional[str] = None
    recording_duration_sec: float = 0.0
    recording_started_at_ms: int = 0
    captured_at_ms: int = 0
    job_id: str = field(default_factory=lambda: f"job-{uuid4()}")


class ComputeClient(ABC):
    @abstractmethod
    async def submit_audio(self, job: AudioAnalyzeJob) -> None: ...

    @abstractmethod
    async def submit_time(self, job: TimeAnalyzeJob) -> None: ...

    @abstractmethod
    async def submit_space(self, job: SpaceAnalyzeJob) -> None: ...


class HttpComputeClient(ComputeClient):
    """真的把任务 POST 给算力服务；提交本身也是"发完即走"，不等处理结果。

    本期不做重试：提交失败只记警告日志，记忆保持 processing，可接受(见协议文档"简化"一节)。
    """

    def __init__(self, base_url: str, callback_base_url: str, internal_token: str):
        self.base_url = base_url.rstrip("/")
        self.callback_base_url = callback_base_url.rstrip("/")
        self.internal_token = internal_token

    def _callback_url(self, kind: str) -> str:
        return f"{self.callback_base_url}/api/v1/internal/callback/{kind}"

    async def _post(self, path: str, payload: dict[str, Any], log_ctx: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=_SUBMIT_TIMEOUT_SECONDS) as client:
                resp = await client.post(f"{self.base_url}{path}", json=payload)
                resp.raise_for_status()
            log.info("已提交算力任务 %s job=%s", log_ctx, payload.get("job_id"))
        except Exception as exc:
            log.warning("提交算力任务失败(不影响主流程) %s job=%s: %s", log_ctx, payload.get("job_id"), exc)

    async def submit_audio(self, job: AudioAnalyzeJob) -> None:
        await self._post(
            "/analyze/audio",
            {
                "job_id": job.job_id,
                "memory_id": str(job.memory_id),
                "session_id": str(job.session_id),
                "partition": job.partition.value,
                "inputs": {"audio_paths": job.audio_paths},
                "callback_url": self._callback_url("audio"),
            },
            f"session={job.session_id} memory={job.memory_id} type=audio",
        )

    async def submit_time(self, job: TimeAnalyzeJob) -> None:
        await self._post(
            "/analyze/time",
            {
                "job_id": job.job_id,
                "memory_id": str(job.memory_id),
                "session_id": str(job.session_id),
                "partition": job.partition.value,
                "inputs": {
                    "video_path": job.video_path,
                    "audio_paths": job.audio_paths,
                    "models_root": job.models_root,
                    "lrasd_root": job.lrasd_root,
                    "output_root": job.output_root,
                },
                "callback_url": self._callback_url("time"),
            },
            f"session={job.session_id} memory={job.memory_id} type=time",
        )

    async def submit_space(self, job: SpaceAnalyzeJob) -> None:
        await self._post(
            "/analyze/space",
            {
                "job_id": job.job_id,
                "memory_id": str(job.memory_id),
                "session_id": str(job.session_id),
                "partition": job.partition.value,
                "inputs": {
                    "video_path": job.video_path,
                    "imu_path": job.imu_path,
                    "scene_type": job.scene_type,
                    "recording_duration_sec": job.recording_duration_sec,
                    "recording_started_at_ms": job.recording_started_at_ms,
                    "captured_at_ms": job.captured_at_ms,
                },
                "callback_url": self._callback_url("space"),
            },
            f"session={job.session_id} memory={job.memory_id} type=space",
        )


class MockComputeClient(ComputeClient):
    """本地直接回填假结果，不发真实网络请求，便于无算力服务时联调/跑测试。

    每次提交都开一个新的 DB 会话调用与真实回调路由完全相同的落库函数，模拟"提交后不久
    收到回调"的效果，但同步完成（对调用方而言就是 complete 请求内就已经落库完毕）。
    """

    async def submit_audio(self, job: AudioAnalyzeJob) -> None:
        log.info(
            "[mock] 算力任务(audio) 立即回填 job=%s session=%s memory=%s",
            job.job_id, job.session_id, job.memory_id,
        )
        async with async_session_factory() as db:
            repo = MemoryRepository(db)
            # Mock 结果留空转写：与此前 store-only 模式(不跑 ASR)行为一致，保证离线/测试环境
            # 确定性；真实转写效果需要接 compute_provider_mode=http 的真实算力服务验证。
            await apply_audio_result(repo, job.memory_id, "succeeded", {"transcript": ""})

    async def submit_time(self, job: TimeAnalyzeJob) -> None:
        log.info(
            "[mock] 算力任务(time) 立即回填占位结果 job=%s session=%s memory=%s",
            job.job_id, job.session_id, job.memory_id,
        )
        async with async_session_factory() as db:
            repo = MemoryRepository(db)
            await apply_time_result(repo, job.memory_id, "succeeded", {"identify_brief": "(mock 占位结果)"})

    async def submit_space(self, job: SpaceAnalyzeJob) -> None:
        log.info(
            "[mock] 算力任务(space) 立即回填占位结果 job=%s session=%s memory=%s",
            job.job_id, job.session_id, job.memory_id,
        )
        async with async_session_factory() as db:
            repo = MemoryRepository(db)
            await apply_space_result(
                repo, job.memory_id, "succeeded",
                {"identify_brief": "(mock 占位结果)", "quality": "good"},
            )


@lru_cache
def get_compute_client() -> ComputeClient:
    settings = get_settings()
    if settings.compute_provider_mode == "http":
        return HttpComputeClient(
            base_url=settings.compute_base_url,
            callback_base_url=settings.public_callback_base_url,
            internal_token=settings.internal_token,
        )
    return MockComputeClient()


# --- 回调结果落库：供 /internal/callback/* 路由与 MockComputeClient 共用 ---

async def apply_audio_result(
    repo: MemoryRepository,
    memory_id: UUID,
    status: str,
    result: dict[str, Any],
    providers: ProviderFactory | None = None,
) -> None:
    memory = await repo.get_time_memory(memory_id)
    if not memory:
        log.warning("语音分析回调:记忆不存在 memory=%s", memory_id)
        return
    if status != "succeeded":
        await repo.update_time_memory(memory_id, status=MemoryStatus.FAILED)
        log.warning("语音分析失败 memory=%s session=%s", memory_id, memory.session_id)
        return

    transcript = ((result or {}).get("transcript") or "").strip()
    if transcript:
        providers = providers or get_provider_factory()
        await repo.delete_evidences_by_type(memory_id, EvidenceType.TRANSCRIPT)
        ev = Evidence(
            memory_id=memory_id,
            type=EvidenceType.TRANSCRIPT,
            content=transcript,
            timestamp_ms=0,
            confidence=ConfidenceLevel.HIGH,
        )
        await repo.save_evidence(ev)
        embedding = providers.embedding()
        vector_store = providers.vector_store()
        emb = await embedding.embed(transcript)
        await vector_store.upsert(
            str(ev.id),
            emb.vector,
            {"memory_id": str(memory_id), "partition": memory.partition.value, "type": "transcript"},
        )

    await repo.update_time_memory(
        memory_id,
        status=MemoryStatus.COMPLETED,
        evidence_status="ready" if transcript else memory.evidence_status,
    )
    if memory.session_id:
        await repo.link_session_memory(memory.session_id, memory_id, MemoryStatus.COMPLETED)
    log.info(
        "语音分析回调完成 memory=%s session=%s transcript_len=%d",
        memory_id, memory.session_id, len(transcript),
    )


async def apply_time_result(
    repo: MemoryRepository,
    memory_id: UUID,
    status: str,
    result: dict[str, Any],
    providers: ProviderFactory | None = None,
) -> None:
    memory = await repo.get_time_memory(memory_id)
    if not memory:
        log.warning("时间记忆回调:记忆不存在 memory=%s", memory_id)
        return
    if status != "succeeded":
        await repo.update_time_memory(memory_id, status=MemoryStatus.FAILED)
        log.warning("时间记忆分析失败 memory=%s session=%s", memory_id, memory.session_id)
        return

    result = result or {}
    providers = providers or get_provider_factory()
    avatar_urls = await _publish_time_memory_faces(
        providers,
        memory_id,
        result.get("faces"),
    )
    result = normalize_time_result(result, avatar_urls=avatar_urls)
    nav_summary = None
    if isinstance(result.get("navigation_summary"), dict):
        try:
            nav_summary = NavigationSummary(**result["navigation_summary"])
        except Exception as exc:
            log.warning("时间记忆回调 navigation_summary 解析失败 memory=%s: %s", memory_id, exc)

    identify_brief = result.get("identify_brief") or None
    key_frames = result.get("key_frames") if isinstance(result.get("key_frames"), list) else None

    await repo.update_time_memory(
        memory_id,
        status=MemoryStatus.COMPLETED,
        identify_brief=identify_brief,
        navigation_summary=nav_summary,
        key_frames=key_frames,
        evidence_status="ready" if (identify_brief or key_frames) else None,
    )
    if memory.session_id:
        await repo.link_session_memory(memory.session_id, memory_id, MemoryStatus.COMPLETED)

    events, faces = result.get("events") or [], result.get("faces") or []
    if events or faces:
        log.info(
            "时间记忆回调含 events/faces memory=%s events=%d faces=%d",
            memory_id, len(events), len(faces),
        )

    transcript = str(
        (result.get("audio_evidence") or {}).get("transcript")
        or " ".join(
            str(item.get("text") or item.get("content") or "")
            for item in result.get("conversation") or []
        )
    ).strip()
    if transcript:
        await repo.delete_evidences_by_type(memory_id, EvidenceType.TRANSCRIPT)
        ev = Evidence(
            memory_id=memory_id,
            type=EvidenceType.TRANSCRIPT,
            content=transcript,
            timestamp_ms=0,
            confidence=ConfidenceLevel.HIGH,
        )
        await repo.save_evidence(ev)
        embedding = providers.embedding()
        vector_store = providers.vector_store()
        emb = await embedding.embed(transcript)
        await vector_store.upsert(
            str(ev.id),
            emb.vector,
            {"memory_id": str(memory_id), "partition": memory.partition.value, "type": "transcript"},
        )

    log.info("时间记忆分析回调完成 memory=%s session=%s", memory_id, memory.session_id)


async def _publish_time_memory_faces(
    providers: ProviderFactory,
    memory_id: UUID,
    faces: Any,
) -> dict[str, str]:
    if not isinstance(faces, list):
        return {}

    blob = providers.blob_store()
    avatar_urls: dict[str, str] = {}
    for index, face in enumerate(faces, 1):
        if not isinstance(face, dict):
            continue
        name = str(face.get("name") or face.get("speaker") or f"speaker-{index}")
        existing_url = face.get("avatar_url")
        if existing_url:
            avatar_urls[name] = str(existing_url)
            continue
        crop_path = face.get("crop_path") or face.get("path")
        if not crop_path:
            continue
        path = Path(str(crop_path)).expanduser()
        if not path.is_file():
            log.warning("时间记忆头像文件不存在 memory=%s path=%s", memory_id, path)
            continue
        suffix = path.suffix.lower() if path.suffix else ".jpg"
        key = f"time-memory/{memory_id}/faces/{index}-{_safe_media_name(name)}{suffix}"
        try:
            await blob.save(key, path.read_bytes(), "image/jpeg")
        except OSError as exc:
            log.warning("时间记忆头像保存失败 memory=%s path=%s: %s", memory_id, path, exc)
            continue
        avatar_urls[name] = blob.get_url(key)
    return avatar_urls


def _safe_media_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)[:80] or "speaker"


def _segment_entry(segment: dict[str, Any], index: int, avatar_urls: dict[str, str]) -> dict[str, Any]:
    speaker = str(
        segment.get("speaker")
        or segment.get("participant_id")
        or segment.get("name")
        or "unknown"
    )
    text = str(segment.get("text") or segment.get("content") or "")
    start_raw = segment.get("start_ms")
    if start_raw is None:
        start_raw = float(segment.get("start") or segment.get("start_sec") or 0) * 1000
    entry = {
        "type": "transcript",
        "segment_id": str(segment.get("segment_id") or f"segment-{index}"),
        "participant_id": str(segment.get("participant_id") or speaker),
        "name": str(segment.get("name") or speaker),
        "content": text,
        "timestamp_ms": round(float(start_raw or 0)),
    }
    person_id = segment.get("person_id")
    avatar_url = segment.get("avatar_url") or avatar_urls.get(speaker)
    if person_id:
        entry["person_id"] = person_id
    if avatar_url:
        entry["avatar_url"] = avatar_url
    return entry


def normalize_time_result(
    result: dict[str, Any],
    *,
    avatar_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Normalize demo/future time-memory output to the phone evidence contract."""
    normalized = dict(result or {})
    avatar_urls = avatar_urls or {}
    navigation = dict(normalized.get("navigation_summary") or {})
    entries: list[dict[str, Any]] = []

    participants = normalized.get("participants") or []
    for index, participant in enumerate(participants, 1):
        if isinstance(participant, str):
            participant = {"name": participant}
        if not isinstance(participant, dict):
            continue
        name = str(participant.get("name") or participant.get("speaker") or f"speaker-{index}")
        entries.append(
            {
                "type": "participant",
                "participant_id": str(participant.get("participant_id") or name),
                "person_id": participant.get("person_id"),
                "name": name,
                "avatar_url": participant.get("avatar_url") or avatar_urls.get(name),
            }
        )

    highlights = normalized.get("conversation_highlights") or normalized.get("highlights") or []
    for index, highlight in enumerate(highlights, 1):
        if not isinstance(highlight, dict):
            continue
        participant = highlight.get("participant") if isinstance(highlight.get("participant"), dict) else {}
        name = str(
            highlight.get("name")
            or highlight.get("speaker")
            or participant.get("name")
            or "unknown"
        )
        entries.append(
            {
                "type": "conversation_highlight",
                "highlight_id": str(highlight.get("highlight_id") or f"highlight-{index}"),
                "participant_id": str(highlight.get("participant_id") or participant.get("participant_id") or name),
                "person_id": highlight.get("person_id") or participant.get("person_id"),
                "name": name,
                "avatar_url": highlight.get("avatar_url") or participant.get("avatar_url") or avatar_urls.get(name),
                "emotion": highlight.get("emotion") or highlight.get("mood") or "neutral",
                "content": str(highlight.get("content") or highlight.get("text") or ""),
                "timestamp_ms": round(float(highlight.get("timestamp_ms") or 0)),
            }
        )

    segments = normalized.get("transcript_segments") or normalized.get("conversation") or []
    if not segments:
        segments = [entry for entry in navigation.get("evidence_entries") or [] if isinstance(entry, dict) and entry.get("type") == "transcript"]
    for index, segment in enumerate(segments, 1):
        if isinstance(segment, dict):
            entries.append(_segment_entry(segment, index, avatar_urls))

    known_names = {entry.get("name") for entry in entries if entry.get("type") == "participant"}
    for name, avatar_url in avatar_urls.items():
        if name not in known_names:
            entries.insert(
                0,
                {"type": "participant", "participant_id": name, "name": name, "avatar_url": avatar_url},
            )

    events = normalized.get("events") or []
    key_moments: list[dict[str, Any]] = []
    for index, moment in enumerate(navigation.get("key_moments") or [], 1):
        if not isinstance(moment, dict):
            continue
        timestamp_ms = int(moment.get("timestamp_ms") or 0)
        key_moments.append(
            {
                "id": str(moment.get("id") or f"moment-{index}"),
                "label": str(moment.get("label") or moment.get("description") or "关键瞬间"),
                "time_offset_seconds": int(moment.get("time_offset_seconds") or timestamp_ms // 1000),
            }
        )
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            continue
        timestamp_ms = int(event.get("start_ms") or event.get("timestamp_ms") or 0)
        key_moments.append(
            {
                "id": str(event.get("id") or f"event-{index}"),
                "label": str(event.get("label") or event.get("task") or event.get("event_type") or "关键事件"),
                "time_offset_seconds": timestamp_ms // 1000,
            }
        )

    navigation["key_moments"] = key_moments
    navigation["evidence_entries"] = entries
    normalized["navigation_summary"] = navigation
    return normalized


async def apply_space_result(
    repo: MemoryRepository, memory_id: UUID, status: str, result: dict[str, Any]
) -> None:
    memory = await repo.get_space_memory(memory_id)
    if not memory:
        log.warning("空间记忆回调:记忆不存在 memory=%s", memory_id)
        return
    if status != "succeeded":
        await repo.update_space_memory(
            memory_id, status=MemoryStatus.FAILED, quality=SpaceQuality.RETRY_REQUIRED
        )
        log.warning("空间记忆分析失败 memory=%s session=%s", memory_id, memory.session_id)
        return

    result = result or {}
    quality_map = {
        "excellent": SpaceQuality.EXCELLENT,
        "good": SpaceQuality.GOOD,
        "retry_required": SpaceQuality.RETRY_REQUIRED,
    }
    quality = quality_map.get(result.get("quality"), None)

    # 单一物体 anchor 坐标（COLMAP 世界坐标系）——手机端物体环绕模式需要。
    anchor = result.get("anchor") or {}
    anchor_pos = anchor.get("position") or {}

    await repo.update_space_memory(
        memory_id,
        status=MemoryStatus.COMPLETED,
        quality=quality,
        model_url=result.get("model_url"),
        model_format=result.get("model_format"),
        loop_angle=result.get("loop_angle"),
        scene_summary=result.get("scene_summary"),
        identify_brief=result.get("identify_brief") or None,
        # 位姿轨迹 + anchor 相关字段（compute FastGS 产出），手机端渲染依赖：
        poses_url=result.get("poses_url"),
        poses_sha256=result.get("poses_sha256"),
        pose_count=result.get("pose_count"),
        anchor_url=result.get("anchor_url"),
        anchor_sha256=result.get("anchor_sha256"),
        anchor_method=anchor.get("method") or result.get("anchor_method"),
        anchor_position_x=float(anchor_pos.get("x", 0.0)),
        anchor_position_y=float(anchor_pos.get("y", 0.0)),
        anchor_position_z=float(anchor_pos.get("z", 0.0)),
        # scene_type/recording_duration_sec 在创建时已写入，回调可覆盖为算力算出的准确值。
        scene_type=result.get("scene_type") or memory.scene_type,
        recording_duration_sec=float(
            result.get("recording_duration_sec") or memory.recording_duration_sec or 0.0
        ),
    )
    if memory.session_id:
        await repo.link_session_memory(memory.session_id, memory_id, MemoryStatus.COMPLETED)

    # anchors（多锚点列表）结构未与实现方钉死，且 SpaceMemoryORM.anchors 需要专门的 JSON 序列化写法，
    # 本期先只记日志，落库留给后续接入时一起做。
    if result.get("anchors"):
        log.info(
            "空间记忆回调含 anchors 列表(占位,暂不落库) memory=%s count=%d",
            memory_id, len(result.get("anchors") or []),
        )
    log.info(
        "空间记忆分析回调完成 memory=%s session=%s poses=%s anchor_method=%s scene_type=%s",
        memory_id, memory.session_id, result.get("pose_count"),
        anchor.get("method"), result.get("scene_type"),
    )
