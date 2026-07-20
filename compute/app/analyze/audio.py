"""语音分析：本期唯一真实实现，逻辑迁自 backend 原 `_transcribe_all_audio` + `WhisperASRProvider`。

拼接所有 PCM 音频块 -> 合成单个 WAV(16k/单声道/16bit) -> 调一次 Whisper -> 输出全量转写文本
-> 回调后台。契约见 docs/protocols/compute-service.md「接口①A / 接口②A」。
"""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from typing import Any

from app.callback import send_callback
from app.logging_setup import get_session_logger
from app.openai_client import whisper_transcribe
from app.settings import get_settings

_SAMPLE_RATE = 16000
_CHANNELS = 1
_SAMPLE_WIDTH = 2


async def run_audio_analysis(
    job_id: str,
    memory_id: str,
    session_id: str,
    inputs: dict[str, Any],
    callback_url: str,
) -> None:
    log = get_session_logger("analyze.audio", session_id)
    audio_paths: list[str] = inputs.get("audio_paths") or []
    log.info("开始语音分析 job=%s memory=%s 音频块数=%d", job_id, memory_id, len(audio_paths))
    try:
        transcript = await _transcribe_all(audio_paths, log)
        log.info(
            "语音转写完成 job=%s memory=%s 文本长度=%d 文本=%r",
            job_id, memory_id, len(transcript), transcript,
        )
        await send_callback(
            callback_url, job_id, memory_id, "succeeded",
            {"transcript": transcript}, session_id=session_id,
        )
    except Exception as exc:
        log.exception("语音分析失败 job=%s memory=%s: %s", job_id, memory_id, exc)
        await send_callback(
            callback_url, job_id, memory_id, "failed",
            {}, error=str(exc), session_id=session_id,
        )


async def _transcribe_all(audio_paths: list[str], log) -> str:
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
            w.setnchannels(_CHANNELS)
            w.setsampwidth(_SAMPLE_WIDTH)
            w.setframerate(_SAMPLE_RATE)
            w.writeframes(bytes(pcm))

        settings = get_settings()
        data = await whisper_transcribe(
            settings.asr_base_url,
            settings.asr_api_key,
            settings.asr_model,
            wav_path,
            settings.asr_language,
            settings.request_timeout_seconds,
        )
        segments = data.get("segments") or []
        texts = [(seg.get("text") or "").strip() for seg in segments]
        texts = [t for t in texts if t]
        if not texts and data.get("text"):
            texts = [data["text"].strip()]
        return " ".join(texts).strip()
    finally:
        Path(wav_path).unlink(missing_ok=True)
