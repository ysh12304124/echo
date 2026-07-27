from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from app.domain.enums import (
    DataPartition,
    MemoryStatus,
    MemoryType,
    TimeScene,
)
from app.domain.models import (
    ImuSample,
    IngestSession,
    SpaceMemory,
    TimeMemory,
)
from app.logging_setup import get_logger
from app.providers import ProviderFactory, get_provider_factory
from app.repositories.memory_repo import MemoryRepository
from app.services.compute_client import (
    ComputeClient,
    SpaceAnalyzeJob,
    TimeAnalyzeJob,
    get_compute_client,
)

log = get_logger("ingest")

# 按 session 序列化视频分片的 append+rename：IngestPipeline 每次请求都会重新构造实例，
# 故用模块级字典保存锁，防止手机端并发/乱序上传（或重复上报）导致分片错序、成片被截断。
_video_append_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class IngestPipeline:
    def __init__(
        self,
        repo: MemoryRepository,
        providers: ProviderFactory | None = None,
        compute_client: ComputeClient | None = None,
    ):
        self.repo = repo
        self.providers = providers or get_provider_factory()
        self.compute_client = compute_client or get_compute_client()

    async def create_session(
        self,
        memory_type: MemoryType,
        scene: TimeScene | None = None,
        scene_type: str | None = None,
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
            scene_type=scene_type,
            partition=partition,
            status=MemoryStatus.RECORDING,
            title=title,
        )
        await self.repo.create_session(session)
        return session

    async def upload_audio(self, session_id: UUID, data: bytes, timestamp_ms: int) -> UUID:
        session = await self.repo.get_session(session_id)
        if not session:
            raise ValueError("Session not found")

        blob = self.providers.blob_store()
        key = f"sessions/{session_id}/audio/{uuid4()}.pcm"
        path = await blob.save(key, data, "audio/pcm")
        await self.repo.update_session_audio(session_id, path)
        return uuid4()

    async def append_imu_samples(self, session_id: UUID, samples: list[ImuSample]) -> int:
        """空间记忆(IMU)批量上报：仅追加写 JSONL 文件，与 video/audio 一样落到会话目录下，
        不入库(当前不跑 loop-detect/空间重建，避免多写一份无人消费的数据)。
        """
        session = await self.repo.get_session(session_id)
        if not session:
            raise ValueError("Session not found")

        if samples:
            lines = "".join(sample.model_dump_json() + "\n" for sample in samples)
            blob = self.providers.blob_store()
            key = f"sessions/{session_id}/imu/imu.jsonl"
            await blob.append(key, lines.encode("utf-8"))

        return len(samples)

    async def append_video_chunk(
        self,
        session_id: UUID,
        index: int,
        is_last: bool,
        filename: str | None,
        data: bytes,
    ) -> Optional[str]:
        """眼镜边录边发、手机不落地转发的视频分片，按到达顺序 append 到会话视频文件。

        用会话级锁串行化 append/rename：即便客户端因重连重复上报或并发乱序导致分片交错到达，
        也不会出现"末片先到触发 rename、前面分片还没写完"而把成片截断的问题。
        """
        session = await self.repo.get_session(session_id)
        if not session:
            raise ValueError("Session not found")

        blob = self.providers.blob_store()
        tmp_key = f"sessions/{session_id}/video/current.tmp"
        lock = _video_append_locks[str(session_id)]
        async with lock:
            if data:
                await blob.append(tmp_key, data)

            if not is_last:
                return None

            tmp_path = await blob.get_path(tmp_key)
            final_name = Path(filename or f"{session_id}.mp4").name
            if not final_name or final_name in {".", ".."}:
                raise ValueError("Invalid video filename")

            final_path: Optional[str] = None
            if tmp_path:
                tmp_file = Path(tmp_path)
                if not tmp_file.is_file() or tmp_file.stat().st_size <= 0:
                    raise ValueError("Video file is empty")
                final_path_obj = tmp_file.with_name(final_name)
                tmp_file.rename(final_path_obj)
                final_path = str(final_path_obj)
            else:
                # video_end may be retried by the glasses link. The first end
                # already renamed current.tmp, so the retry must preserve the
                # recorded path instead of overwriting it with an empty value.
                existing_path = await self.repo.get_session_video_path(session_id)
                if existing_path and Path(existing_path).is_file():
                    final_path = existing_path
                else:
                    raise ValueError("Video end received before a video file was uploaded")

            await self.repo.update_session_video(session_id, final_path)
            log.info(
                "视频接收完成 session=%s filename=%s index=%d path=%s",
                session_id, final_name, index, final_path,
            )
        return final_path

    @staticmethod
    def _require_video_file(video_path: Optional[str]) -> str:
        if not video_path:
            raise ValueError("时间记忆缺少视频文件，拒绝提交处理")
        path = Path(video_path)
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"视频文件不存在或为空: {video_path}")
        return str(path)

    async def patch_video_header(self, session_id: UUID, offset: int, data: bytes) -> None:
        """覆盖写视频临时文件头部，修正边录边发时已发出的、MediaRecorder 后续回改过的字节
        （如 mdat box 的 64bit size 占位值）。必须在对应会话收到 video_end(触发 rename)之前调用，
        与 append_video_chunk 共用同一把会话锁，避免与 append/rename 交错。
        """
        session = await self.repo.get_session(session_id)
        if not session:
            raise ValueError("Session not found")
        if not data:
            return

        blob = self.providers.blob_store()
        tmp_key = f"sessions/{session_id}/video/current.tmp"
        lock = _video_append_locks[str(session_id)]
        async with lock:
            try:
                await blob.patch(tmp_key, offset, data)
            except ValueError:
                log.warning("视频头部覆盖跳过(临时文件已不存在，可能已 rename) session=%s", session_id)
                return
        log.info("视频头部已覆盖 session=%s offset=%d bytes=%d", session_id, offset, len(data))

    async def complete_session(self, session_id: UUID) -> TimeMemory | SpaceMemory:
        session = await self.repo.get_session(session_id)
        if not session:
            raise ValueError("Session not found")

        if session.memory_type == MemoryType.TIME:
            return await self._complete_time_session_store_only(session)
        return await self._complete_space_session_store_only(session)

    async def _complete_time_session_store_only(self, session: IngestSession) -> TimeMemory:
        """存储视频/音频后，把完整时间记忆分析异步甩给算力服务，不在这里同步等结果。

        立即创建 status=PROCESSING 的记忆并 return；算力服务处理完通过
        /internal/callback/time 回调本服务把完整结果写入记忆并把状态置为 completed
        （mock 模式下这一步会在 submit_time 内同步完成，效果等同于"秒级完成"）。
        """
        started_at = session.created_at
        ended_at = datetime.now(timezone.utc)
        duration = int((ended_at - _as_utc(started_at)).total_seconds())
        video_path = self._require_video_file(
            await self.repo.get_session_video_path(session.id)
        )
        _, audio_paths = await self.repo.get_session_media_paths(session.id)

        memory = TimeMemory(
            scene=session.scene or TimeScene.MEETING,
            partition=session.partition,
            status=MemoryStatus.PROCESSING,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            identify_brief="",
            evidence_status="pending",
            session_id=session.id,
            title=session.title,
        )
        await self.repo.create_time_memory(memory)
        await self.repo.link_session_memory(session.id, memory.id, MemoryStatus.PROCESSING)
        log.info(
            "时间记忆已创建,等待算力异步分析语音 memory=%s session=%s duration=%ds video=%s audio_chunks=%d",
            memory.id, session.id, duration, video_path, len(audio_paths),
        )

        job = TimeAnalyzeJob(
            memory_id=memory.id,
            session_id=session.id,
            partition=session.partition,
            video_path=video_path,
            audio_paths=audio_paths,
        )
        await self.compute_client.submit_time(job)
        log.info("时间记忆分析任务已提交算力服务 session=%s memory=%s job=%s video=%s audio_chunks=%d", session.id, memory.id, job.job_id, video_path, len(audio_paths))

        return await self.repo.get_time_memory(memory.id) or memory

    async def _complete_space_session_store_only(self, session: IngestSession) -> SpaceMemory:
        """存储视频/IMU后，把空间重建异步甩给算力服务(接口①C)，不在这里同步等结果。

        立即创建 status=PROCESSING 的记忆并 return；算力服务处理完通过
        /internal/callback/space 回调本服务把重建结果写入并把状态置为 completed
        （mock 模式下这一步会在 submit_space 内同步完成，效果等同于"秒级完成"）。
        """
        existing = await self.repo.get_space_memory(session.memory_id) if session.memory_id else None
        if existing:
            return existing

        video_path = await self.repo.get_session_video_path(session.id)
        blob = self.providers.blob_store()
        imu_path = await blob.get_path(f"sessions/{session.id}/imu/imu.jsonl")

        # 采集时长（秒）：从会话创建时间到现在，供渲染层计算移动速度基准。
        duration_sec = max(
            0.0, (datetime.now(timezone.utc) - _as_utc(session.created_at)).total_seconds()
        )

        captured_at = datetime.now(timezone.utc)
        memory = SpaceMemory(
            partition=session.partition,
            status=MemoryStatus.PROCESSING,
            captured_at=captured_at,
            identify_brief=session.title or "空间采集，正在分析",
            session_id=session.id,
            title=session.title or "空间记忆",
            scene_type=session.scene_type,
            recording_duration_sec=duration_sec,
            recording_started_at_ms=int(_as_utc(session.created_at).timestamp() * 1000),
            captured_at_ms=int(captured_at.timestamp() * 1000),
        )
        await self.repo.create_space_memory(memory)
        await self.repo.link_session_memory(session.id, memory.id, MemoryStatus.PROCESSING)
        log.info(
            "空间记忆已创建,等待算力异步重建 memory=%s session=%s scene_type=%s duration=%.1fs video=%s imu=%s",
            memory.id, session.id, session.scene_type, duration_sec, video_path, imu_path,
        )

        job = SpaceAnalyzeJob(
            memory_id=memory.id,
            session_id=session.id,
            partition=session.partition,
            video_path=video_path,
            imu_path=imu_path,
            scene_type=session.scene_type,
            recording_duration_sec=duration_sec,
        )
        await self.compute_client.submit_space(job)
        log.info("空间分析任务已提交算力服务 session=%s memory=%s job=%s", session.id, memory.id, job.job_id)

        return await self.repo.get_space_memory(memory.id) or memory
