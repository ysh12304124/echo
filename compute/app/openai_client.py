"""极简的 OpenAI 兼容 Whisper 客户端，仅供 analyze/audio.py 使用。"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional

import httpx


async def whisper_transcribe(
    base_url: str,
    api_key: str,
    model: str,
    audio_path: str,
    language: Optional[str],
    timeout: float,
) -> dict:
    """调用 /audio/transcriptions，请求 verbose_json 以获取分段。"""
    path = Path(audio_path)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    form: dict = {
        "model": (None, model),
        "response_format": (None, "verbose_json"),
        "timestamp_granularities[]": (None, "segment"),
    }
    if language:
        form["language"] = (None, language)

    async with httpx.AsyncClient(timeout=timeout) as client:
        with path.open("rb") as f:
            files = {"file": (path.name, f, content_type), **form}
            resp = await client.post(
                f"{base_url.rstrip('/')}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
            )
        resp.raise_for_status()
        return resp.json()
