"""语音分析：本期唯一真实实现，逻辑迁自 backend 原 `_transcribe_all_audio` + `WhisperASRProvider`。

拼接所有 PCM 音频块 -> 合成单个 WAV(16k/单声道/16bit) -> 调一次 Whisper -> 输出全量转写文本
-> 回调后台。契约见 docs/protocols/compute-service.md「接口①A / 接口②A」。
"""

from __future__ import annotations

import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.callback import send_callback
from app.logging_setup import get_session_logger
from app.openai_client import whisper_transcribe
from app.settings import get_settings

_SAMPLE_RATE = 16000
_CHANNELS = 1
_SAMPLE_WIDTH = 2


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    duration_ms: int
    avg_logprob: float | None


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
        transcription = await transcribe_pcm(audio_paths)
        transcript = transcription.text
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
    return (await transcribe_pcm(audio_paths, log=log)).text


async def transcribe_pcm(
    audio_paths: list[str],
    sample_rate: int = _SAMPLE_RATE,
    channels: int = _CHANNELS,
    sample_width: int = _SAMPLE_WIDTH,
    log=None,
) -> TranscriptionResult:
    """Combine PCM files, call Whisper once, and preserve ASR confidence metadata."""
    if not audio_paths:
        return TranscriptionResult(text="", duration_ms=0, avg_logprob=None)
    pcm = bytearray()
    for p in audio_paths:
        try:
            pcm += Path(p).read_bytes()
        except OSError as e:
            if log:
                log.warning("读取音频块失败 %s: %s", p, e)
    if not pcm:
        return TranscriptionResult(text="", duration_ms=0, avg_logprob=None)

    bytes_per_second = sample_rate * channels * sample_width
    duration_ms = int(len(pcm) / bytes_per_second * 1000)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(sample_width)
            w.setframerate(sample_rate)
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
        return TranscriptionResult(
            text=" ".join(texts).strip(),
            duration_ms=duration_ms,
            avg_logprob=_weighted_avg_logprob(segments),
        )
    finally:
        Path(wav_path).unlink(missing_ok=True)


def _weighted_avg_logprob(segments: list[dict]) -> float | None:
    weighted_sum = 0.0
    total_weight = 0.0
    fallback: list[float] = []
    for segment in segments:
        value = segment.get("avg_logprob")
        if not isinstance(value, (int, float)):
            continue
        numeric = float(value)
        fallback.append(numeric)
        start = segment.get("start")
        end = segment.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            weight = max(float(end) - float(start), 0.0)
            if weight > 0.0:
                weighted_sum += numeric * weight
                total_weight += weight
    if total_weight > 0.0:
        return weighted_sum / total_weight
    if fallback:
        return sum(fallback) / len(fallback)
    return None
