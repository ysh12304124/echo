"""Whisper ASR 服务：用 faster-whisper 跑推理，对外暴露 OpenAI 兼容的
`/v1/audio/transcriptions` 接口，供 compute/app/openai_client.py 直接调用
（与 backend 原来接的远程 Whisper 服务、以及 backend 自身 provider 用的形状完全一致）。

启动: ./start.sh（默认后台运行，日志写 log/asr.log），默认端口 8081。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import PlainTextResponse

from logging_setup import get_logger, setup_logging

setup_logging()
log = get_logger("server")

MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "medium")
DEVICE = os.environ.get("WHISPER_DEVICE", "auto")  # auto|cuda|cpu
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "default")  # default|float16|int8|int8_float16...
DOWNLOAD_ROOT = os.environ.get("WHISPER_DOWNLOAD_ROOT", str(Path(__file__).parent / "weights"))

app = FastAPI(title="Whisper ASR Server (OpenAI 兼容)")

_model = None


def get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        log.info("加载模型 %s device=%s compute_type=%s ...", MODEL_SIZE, DEVICE, COMPUTE_TYPE)
        _model = WhisperModel(
            MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE, download_root=DOWNLOAD_ROOT
        )
        log.info("模型加载完成")
    return _model


@app.on_event("startup")
async def _warmup() -> None:
    # 启动即加载模型，避免第一个真实请求还要等模型加载。
    get_model()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model": MODEL_SIZE, "device": DEVICE}


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    response_format: str = Form("json"),
    language: Optional[str] = Form(None),
):
    """形状对齐 OpenAI `/v1/audio/transcriptions`：`model`/`timestamp_granularities[]` 等
    额外字段会被忽略，只按 `response_format=verbose_json` 时返回带 `segments` 的结构。
    """
    data = await file.read()
    log.info("收到转写请求 bytes=%d model=%s language=%s", len(data), model, language)
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        whisper = get_model()
        segments_iter, info = whisper.transcribe(tmp_path, language=language, vad_filter=True)
        segments = []
        texts = []
        for i, seg in enumerate(segments_iter):
            text = seg.text.strip()
            if not text:
                continue
            texts.append(text)
            segments.append(
                {
                    "id": i,
                    "start": seg.start,
                    "end": seg.end,
                    "text": text,
                    "avg_logprob": seg.avg_logprob,
                }
            )
        full_text = " ".join(texts).strip()
        log.info("转写完成 duration=%.1fs 文本长度=%d", info.duration, len(full_text))

        if response_format == "text":
            return PlainTextResponse(full_text)
        return {
            "text": full_text,
            "language": info.language,
            "duration": info.duration,
            "segments": segments,
        }
    finally:
        Path(tmp_path).unlink(missing_ok=True)
