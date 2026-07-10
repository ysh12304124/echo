from __future__ import annotations

import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
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
    IngestSession,
    NavigationSummary,
    SpaceAnchor,
    SpaceMemory,
    TimeMemory,
)
from app.logging_setup import get_logger
from app.providers import ProviderFactory, get_provider_factory
from app.repositories.memory_repo import MemoryRepository

log = get_logger("ingest")

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

    async def upload_frame(
        self, session_id: UUID, data: bytes, timestamp_ms: int, is_key_moment: bool = False
    ) -> tuple[UUID, bool, bool]:
        session = await self.repo.get_session(session_id)
        if not session:
            raise ValueError("Session not found")

        blob = self.providers.blob_store()
        frame_id = uuid4()
        filename = f"{frame_id}.jpg"
        key = f"sessions/{session_id}/frames/{filename}"
        path = await blob.save(key, data, "image/jpeg")

        # 按接收顺序保存全部帧，确保 complete 时能取到「收到的第一张图片」。
        await self.repo.update_session_frames(session_id, path)
        return frame_id, True, False

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
            captured_at=datetime.now(timezone.utc),
            identify_brief=session.title or "空间采集",
            session_id=session.id,
            title=session.title or "空间记忆",
        )
        for a in anchors:
            a.space_id = memory.id

        await self.repo.create_space_memory(memory)
        await self.repo.link_session_memory(session.id, memory.id, memory.status)
        return memory
