"""Echo 算力服务 —— 独立进程，与 backend 同机通过 localhost 通信，共享本地磁盘。

三个提交端点(`/analyze/audio|time|space`)收到请求即校验参数、返回 `202 {job_id}`，
用 FastAPI BackgroundTask 跑内部逻辑，完成后主动回调后台。契约详见
docs/protocols/compute-service.md。
"""

from __future__ import annotations

from typing import Any

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel, Field

from app.analyze.audio import run_audio_analysis
from app.analyze.space_memory import run_space_analysis
from app.analyze.time_memory import run_time_analysis
from app.logging_setup import get_logger, setup_logging

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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
