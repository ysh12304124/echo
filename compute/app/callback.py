"""算力处理完成后，回调后台服务落库(见 docs/protocols/compute-service.md「接口②」)。

本期不做重试：回调失败只记警告日志，后台记忆会停在 processing，可接受。
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from app.logging_setup import get_logger
from app.settings import get_settings

log = get_logger("callback")


async def send_callback(
    callback_url: str,
    job_id: str,
    memory_id: str,
    status: str,
    result: dict[str, Any],
    error: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    settings = get_settings()
    payload = {
        "job_id": job_id,
        "memory_id": memory_id,
        "status": status,
        "result": result,
        "error": error,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.post(
                callback_url,
                json=payload,
                headers={"X-Internal-Token": settings.internal_token},
            )
            resp.raise_for_status()
        log.info("session=%s 回调后台成功 job=%s memory=%s status=%s", session_id, job_id, memory_id, status)
    except Exception as exc:
        log.warning(
            "session=%s 回调后台失败(不重试,记忆将停在processing) job=%s memory=%s: %s",
            session_id, job_id, memory_id, exc,
        )
