from __future__ import annotations

import asyncio
import tempfile
import wave
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from app.domain.enums import (
    ConfidenceLevel,
    DataPartition,
    EvidenceType,
    MemoryStatus,
    MemoryType,
    SpaceQuality,
    TimeScene,
)
from app.domain.models import (
    Evidence,
    ImuSample,
    IngestSession,
    NavigationSummary,
    SpaceAnchor,
    SpaceMemory,
    TimeMemory,
)
from app.logging_setup import get_logger
from app.providers import ProviderFactory, get_provider_factory
from app.repositories.memory_repo import MemoryRepository
from app.services.spatial import detect_loop

log = get_logger("ingest")

# 按 session 序列化视频分片的 append+rename：IngestPipeline 每次请求都会重新构造实例，
# 故用模块级字典保存锁，防止手机端并发/乱序上传（或重复上报）导致分片错序、成片被截断。
_video_append_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

# 眼镜端音频约定：PCM 16kHz / 单声道 / 16bit（手机端按 1 秒 32000 字节分块上传）。
_AUDIO_SAMPLE_RATE = 16000
_AUDIO_CHANNELS = 1
_AUDIO_SAMPLE_WIDTH = 2
_KEY_FRAME_COUNT = 3


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class IngestPipeline:
    def __init__(self, repo: MemoryRepository, providers: ProviderFactory | None = None):
        self.repo = repo
        self.providers = providers or get_provider_factory()

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
            final_name = filename or f"{session_id}.mp4"
            final_path: Optional[str] = None
            if tmp_path:
                final_path_obj = Path(tmp_path).with_name(final_name)
                Path(tmp_path).rename(final_path_obj)
                final_path = str(final_path_obj)
            await self.repo.update_session_video(session_id, final_path or "")
            log.info(
                "视频接收完成 session=%s filename=%s index=%d path=%s",
                session_id, final_name, index, final_path,
            )
            return final_path

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
        frame_paths, _ = await self.repo.get_session_media_paths(session_id)
        return await self._create_processing_space_memory(session, frame_paths)

    async def _complete_time_session_store_only(self, session: IngestSession) -> TimeMemory:
        """当前阶段仅做存储与结束：不跑 ASR/VLM 摘要，生成最小记忆记录供列表展示。"""
        started_at = session.created_at
        ended_at = datetime.now(timezone.utc)
        duration = int((ended_at - _as_utc(started_at)).total_seconds())
        video_path = await self.repo.get_session_video_path(session.id)
        _, audio_paths = await self.repo.get_session_media_paths(session.id)

        memory = TimeMemory(
            scene=session.scene or TimeScene.MEETING,
            partition=session.partition,
            status=MemoryStatus.COMPLETED,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration,
            identify_brief="",
            evidence_status="pending",
            session_id=session.id,
            title=session.title,
        )
        await self.repo.create_time_memory(memory)
        await self.repo.link_session_memory(session.id, memory.id, MemoryStatus.COMPLETED)
        log.info(
            "时间记忆已保存(仅存储) memory=%s session=%s duration=%ds video=%s audio_chunks=%d",
            memory.id, session.id, duration, video_path, len(audio_paths),
        )
        return memory

    async def _create_processing_space_memory(
        self, session: IngestSession, frame_paths: list[str]
    ) -> SpaceMemory:
        """Persist the space record before the long-running remote job starts."""
        existing = await self.repo.get_space_memory(session.memory_id) if session.memory_id else None
        if existing:
            return existing

        imu_samples = await self.repo.list_imu_samples(session.id)
        loop = detect_loop(imu_samples)
        memory = SpaceMemory(
            partition=session.partition,
            status=MemoryStatus.PROCESSING,
            quality=SpaceQuality.GOOD,
            captured_at=datetime.now(timezone.utc),
            identify_brief=session.title or "空间采集，正在重建",
            loop_angle=loop.angle_degrees,
            session_id=session.id,
            title=session.title or "空间记忆",
        )
        await self.repo.create_space_memory(memory)
        await self.repo.link_session_memory(session.id, memory.id, MemoryStatus.PROCESSING)
        log.info(
            "空间重建任务已创建 session=%s memory=%s frames=%d loop_angle=%.2f",
            session.id, memory.id, len(frame_paths), loop.angle_degrees,
        )
        return memory

    async def run_space_reconstruction(
        self, memory_id: UUID, session_id: UUID, frame_paths: list[str]
    ) -> SpaceMemory:
        """Run remote FastGS and update the already-created space record."""
        memory = await self.repo.get_space_memory(memory_id)
        if not memory:
            raise ValueError("Space memory not found")
        from app.services.remote_reconstruction import RemoteReconstructionService

        try:
            service = RemoteReconstructionService()
            if service.is_configured():
                artifact = await service.reconstruct(
                    session_id=session_id,
                    space_id=memory_id,
                    frame_paths=frame_paths,
                    blob_store=self.providers.blob_store(),
                )
            else:
                # Keep offline/mock development usable until remote FastGS settings exist.
                result = await self.providers.reconstruction().reconstruct(frame_paths)
                model_format = Path(result.model_url).suffix.lower().lstrip(".") or None
                updated = await self.repo.update_space_memory(
                    memory_id,
                    status=MemoryStatus.COMPLETED,
                    quality=SpaceQuality.GOOD,
                    model_url=result.model_url,
                    model_format=model_format,
                    identify_brief="空间重建完成（mock）",
                )
                await self.repo.link_session_memory(session_id, memory_id, MemoryStatus.COMPLETED)
                return updated
            updated = await self.repo.update_space_memory(
                memory_id,
                status=MemoryStatus.COMPLETED,
                quality=SpaceQuality.GOOD,
                model_url=artifact.model_url,
                model_format=artifact.model_format,
                identify_brief="空间重建完成",
            )
            await self.repo.link_session_memory(session_id, memory_id, MemoryStatus.COMPLETED)
            log.info(
                "空间重建完成 session=%s memory=%s job=%s model=%s size=%d sha256=%s",
                session_id, memory_id, artifact.job_id, artifact.model_url,
                artifact.size_bytes, artifact.sha256,
            )
            return updated
        except Exception as exc:
            await self.repo.update_space_memory(
                memory_id,
                status=MemoryStatus.FAILED,
                quality=SpaceQuality.RETRY_REQUIRED,
                identify_brief="空间重建失败，请重新录制",
            )
            await self.repo.link_session_memory(session_id, memory_id, MemoryStatus.FAILED)
            log.exception("空间重建失败 session=%s memory=%s: %s", session_id, memory_id, exc)
            return await self.repo.get_space_memory(memory_id)

    async def _process_time_session(
        self, session: IngestSession, frame_paths: list[str], audio_paths: list[str]
    ) -> TimeMemory:
        memory = TimeMemory(
            scene=session.scene or TimeScene.MEETING,
            partition=session.partition,
            status=MemoryStatus.PROCESSING,
            started_at=session.created_at,
            ended_at=datetime.now(timezone.utc),
            session_id=session.id,
            title=session.title,
        )
        await self.repo.create_time_memory(memory)
        await self.repo.link_session_memory(session.id, memory.id, MemoryStatus.PROCESSING)
        log.info(
            "开始处理时间记忆 memory=%s frames=%d audio_chunks=%d",
            memory.id, len(frame_paths), len(audio_paths),
        )

        asr = self.providers.asr()
        vision = self.providers.vision()
        embedding = self.providers.embedding()
        vector_store = self.providers.vector_store()

        # 1) 所有语音块合并为一整段，只发一次 Whisper ASR 得到全量转写。
        transcript_text = await self._transcribe_all_audio(asr, audio_paths)
        log.info(
            "语音转写完成 memory=%s 文本长度=%d 文本=%r",
            memory.id, len(transcript_text), transcript_text,
        )

        # 2) 全量转写 + 收到的第一张图片 → gemma 得到 人物数量/空间/语音总结。
        first_image = frame_paths[0] if frame_paths else None
        summary = await vision.summarize_session(transcript_text, first_image)
        person_count = int(summary.get("person_count", 0) or 0)
        space = (summary.get("space") or "").strip()
        voice_summary = (summary.get("voice_summary") or "").strip()
        log.info(
            "记忆摘要生成 memory=%s person_count=%d space=%r voice_summary_len=%d",
            memory.id, person_count, space, len(voice_summary),
        )

        # 3) 保存全量转写为证据并建立向量索引，供客户端 /query 检索。
        if transcript_text:
            ev = Evidence(
                memory_id=memory.id,
                type=EvidenceType.TRANSCRIPT,
                content=transcript_text,
                timestamp_ms=0,
                confidence=ConfidenceLevel.HIGH,
            )
            await self.repo.save_evidence(ev)
            emb = await embedding.embed(transcript_text)
            await vector_store.upsert(
                str(ev.id),
                emb.vector,
                {"memory_id": str(memory.id), "partition": memory.partition.value, "type": "transcript"},
            )

        duration = int((datetime.now(timezone.utc) - _as_utc(session.created_at)).total_seconds())
        key_frames = self._select_key_frames(session.id, frame_paths, duration)

        # 组织可读摘要：时间由 started_at/duration 体现，人物数量/空间/语音总结落到展示字段。
        identify_brief = f"共{person_count}人 · 空间：{space or '未知'}｜{voice_summary or '无语音内容'}"
        nav_summary = NavigationSummary(
            persons=[f"{person_count}人"],
            topics=[space] if space else [],
            spaces=[space] if space else [],
        )

        memory = await self.repo.update_time_memory(
            memory.id,
            status=MemoryStatus.COMPLETED,
            identify_brief=identify_brief,
            navigation_summary=nav_summary,
            key_frames=key_frames,
            evidence_status="ready",
            duration_seconds=duration,
            title=memory.title or identify_brief,
            ended_at=datetime.now(timezone.utc),
        )
        await self.repo.link_session_memory(session.id, memory.id, MemoryStatus.COMPLETED)
        log.info("时间记忆已保存 memory=%s duration=%ds", memory.id, duration)
        return memory

    def _select_key_frames(
        self,
        session_id: UUID,
        frame_paths: list[str],
        duration_seconds: int,
    ) -> list[dict]:
        """Persist the selected key frame markers once at complete time."""
        key_frames: list[dict] = []
        if not frame_paths:
            return key_frames

        for index in self._select_key_frame_indexes(len(frame_paths)):
            frame_path = frame_paths[index]
            media_key = self._frame_media_key(session_id, frame_path)
            timestamp_ms = self._estimate_frame_timestamp_ms(
                index, len(frame_paths), duration_seconds
            )
            key_frames.append(
                {
                    "media_path": media_key,
                    "filename": Path(frame_path).name,
                    "frame_index": index,
                    "timestamp_ms": timestamp_ms,
                    "label": "",
                    "description": "",
                }
            )

        return key_frames

    def _select_key_frame_indexes(self, frame_count: int) -> list[int]:
        if frame_count <= 0:
            return []
        selected_count = min(frame_count, _KEY_FRAME_COUNT)
        if frame_count <= _KEY_FRAME_COUNT:
            return list(range(frame_count))
        return [
            round((i + 1) * (frame_count - 1) / (selected_count + 1))
            for i in range(selected_count)
        ]

    def _frame_media_key(self, session_id: UUID, frame_path: str) -> str:
        return f"sessions/{session_id}/frames/{Path(frame_path).name}"

    def _estimate_frame_timestamp_ms(
        self, frame_index: int, frame_count: int, duration_seconds: int
    ) -> int:
        if frame_count <= 1 or duration_seconds <= 0:
            return 0
        return int((frame_index / (frame_count - 1)) * duration_seconds * 1000)

    async def _transcribe_all_audio(self, asr, audio_paths: list[str]) -> str:
        """把所有 PCM 音频块合并成一段 WAV，只调用一次 ASR，返回全量转写文本。"""
        if not audio_paths:
            return ""
        pcm = bytearray()
        for p in audio_paths:
            try:
                pcm += Path(p).read_bytes()
            except OSError as e:
                log.warning("读取音频块失败 %s: %s", p, e)
        if not pcm:
            return ""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            with wave.open(wav_path, "wb") as w:
                w.setnchannels(_AUDIO_CHANNELS)
                w.setsampwidth(_AUDIO_SAMPLE_WIDTH)
                w.setframerate(_AUDIO_SAMPLE_RATE)
                w.writeframes(bytes(pcm))
            segments = await asr.transcribe(wav_path)
            return " ".join(s.text for s in segments if s.text).strip()
        finally:
            Path(wav_path).unlink(missing_ok=True)

    async def _process_space_session(
        self,
        session: IngestSession,
        frame_paths: list[str],
        imu_samples: list[ImuSample],
    ) -> SpaceMemory:
        reconstruction = self.providers.reconstruction()
        result = await reconstruction.reconstruct(frame_paths)

        quality_map = {
            "excellent": SpaceQuality.EXCELLENT,
            "good": SpaceQuality.GOOD,
            "retry_required": SpaceQuality.RETRY_REQUIRED,
        }
        quality = quality_map.get(result.quality, SpaceQuality.GOOD)
        loop = detect_loop(imu_samples)
        model_format = None
        if result.model_url:
            suffix = Path(result.model_url).suffix.lower().lstrip(".")
            model_format = suffix if suffix in {"ply", "splat", "glb"} else None

        anchors = [
            SpaceAnchor(
                space_id=uuid4(),
                name=s["name"],
                anchor_type=s.get("type", "generic"),
                position=s.get("position", {"x": 0, "y": 0, "z": 0}),
            )
            for s in result.anchor_suggestions
        ]

        # VLM 场景描述
        scene_desc = ""
        if frame_paths:
            try:
                vision = self.providers.vision()
                scene_desc = await vision.describe_scene(frame_paths[0])
                log.info("空间记忆场景描述 memory=%s desc=%r", session.id, scene_desc)
            except Exception as e:
                log.warning("场景描述生成失败: %s", e)

        memory = SpaceMemory(
            partition=session.partition,
            status=MemoryStatus.COMPLETED if quality != SpaceQuality.RETRY_REQUIRED else MemoryStatus.FAILED,
            quality=quality,
            model_url=result.model_url,
            anchors=anchors,
            captured_at=datetime.now(timezone.utc),
            identify_brief=scene_desc or session.title or "空间采集",
            model_format=model_format,
            loop_angle=loop.angle_degrees,
            session_id=session.id,
            title=session.title or "空间记忆",
        )
        for a in anchors:
            a.space_id = memory.id

        await self.repo.create_space_memory(memory)
        await self.repo.link_session_memory(session.id, memory.id, memory.status)
        return memory
