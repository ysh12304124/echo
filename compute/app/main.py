"""Echo 算力服务 —— 独立进程，与 backend 同机通过 localhost 通信，共享本地磁盘。

三个提交端点(`/analyze/audio|time|space`)收到请求即校验参数、返回 `202 {job_id}`，
用 FastAPI BackgroundTask 跑内部逻辑，完成后主动回调后台。契约详见
docs/protocols/compute-service.md。
"""

from __future__ import annotations

from typing import Any

from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.analyze.audio import run_audio_analysis, transcribe_pcm
from app.analyze.space_memory import run_space_analysis
from app.analyze.time_memory import run_time_analysis
from app.logging_setup import get_logger, setup_logging
from app.settings import get_settings

setup_logging()
log = get_logger("main")

app = FastAPI(
    title="Echo Compute Service",
    version="1.0.0",
    description="识境 Echo 算力服务：音频转写(真实实现) + 时间/空间记忆分析(桩实现)",
)


class AnalyzeRequest(BaseModel):
    job_id: str
    memory_id: str
    session_id: str
    partition: str = "work"
    inputs: dict[str, Any] = Field(default_factory=dict)
    callback_url: str


class AnalyzeAck(BaseModel):
    job_id: str


class TranscribeRequest(BaseModel):
    audio_path: str
    sample_rate_hz: int = Field(default=16000, ge=8000, le=48000)
    channels: int = Field(default=1, ge=1, le=2)
    sample_width_bytes: int = Field(default=2, ge=1, le=4)


class TranscribeResponse(BaseModel):
    text: str
    duration_ms: int
    avg_logprob: float | None = None


@app.post("/analyze/audio", response_model=AnalyzeAck, status_code=202)
async def analyze_audio(req: AnalyzeRequest, background: BackgroundTasks) -> AnalyzeAck:
    log.info(
        "session=%s 收到语音分析任务 job=%s memory=%s", req.session_id, req.job_id, req.memory_id
    )
    background.add_task(
        run_audio_analysis, req.job_id, req.memory_id, req.session_id, req.inputs, req.callback_url
    )
    return AnalyzeAck(job_id=req.job_id)


@app.post("/analyze/time", response_model=AnalyzeAck, status_code=202)
async def analyze_time(req: AnalyzeRequest, background: BackgroundTasks) -> AnalyzeAck:
    log.info(
        "session=%s 收到时间记忆分析任务(桩) job=%s memory=%s", req.session_id, req.job_id, req.memory_id
    )
    background.add_task(
        run_time_analysis, req.job_id, req.memory_id, req.session_id, req.inputs, req.callback_url
    )
    return AnalyzeAck(job_id=req.job_id)


@app.post("/analyze/space", response_model=AnalyzeAck, status_code=202)
async def analyze_space(req: AnalyzeRequest, background: BackgroundTasks) -> AnalyzeAck:
    log.info(
        "session=%s 收到空间记忆分析任务(桩) job=%s memory=%s", req.session_id, req.job_id, req.memory_id
    )
    background.add_task(
        run_space_analysis, req.job_id, req.memory_id, req.session_id, req.inputs, req.callback_url
    )
    return AnalyzeAck(job_id=req.job_id)


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    req: TranscribeRequest,
    x_internal_token: str | None = Header(default=None),
) -> TranscribeResponse:
    settings = get_settings()
    if x_internal_token != settings.internal_token:
        raise HTTPException(401, "Invalid internal token")
    if (req.sample_rate_hz, req.channels, req.sample_width_bytes) != (16000, 1, 2):
        raise HTTPException(400, "Only 16kHz mono 16-bit PCM is supported")

    root = Path(settings.shared_blob_root).resolve()
    audio_path = Path(req.audio_path).resolve()
    try:
        audio_path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(403, "Audio path is outside the shared blob root") from exc
    if not audio_path.is_file():
        raise HTTPException(404, "Audio file not found")

    size = audio_path.stat().st_size
    if size == 0 or size % req.sample_width_bytes != 0:
        raise HTTPException(400, "Invalid PCM payload")
    duration_seconds = size / (
        req.sample_rate_hz * req.channels * req.sample_width_bytes
    )
    if duration_seconds > settings.max_voice_query_seconds:
        raise HTTPException(400, "Audio duration exceeds configured maximum")

    result = await transcribe_pcm(
        [str(audio_path)],
        sample_rate=req.sample_rate_hz,
        channels=req.channels,
        sample_width=req.sample_width_bytes,
    )
    return TranscribeResponse(
        text=result.text,
        duration_ms=result.duration_ms,
        avg_logprob=result.avg_logprob,
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
