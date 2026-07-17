"""时间记忆分析：本期桩实现。读取输入、记录日志、回填占位 result 并回调。

真实实现(阶段四)：视频抽帧 -> 人脸检测/识别(人脸识别模型) + 关键帧/事件识别(YOLO) ->
关键帧+事件送视觉大模型(VLM)总结 -> 输出 identify_brief/navigation_summary/key_frames/
events/faces。字段需与实现方对齐后钉死，详见 docs/protocols/compute-service.md「接口①B / 接口②B」。
"""

from __future__ import annotations

from typing import Any

from app.callback import send_callback
from app.logging_setup import get_session_logger


async def run_time_analysis(
    job_id: str,
    memory_id: str,
    session_id: str,
    inputs: dict[str, Any],
    callback_url: str,
) -> None:
    log = get_session_logger("analyze.time", session_id)
    video_path = inputs.get("video_path")
    audio_paths: list[str] = inputs.get("audio_paths") or []
    log.info(
        "开始时间记忆分析(桩) job=%s memory=%s video=%s 音频块数=%d",
        job_id, memory_id, video_path, len(audio_paths),
    )

    # TODO(阶段四): 接入人脸检测/识别 + YOLO 关键帧/事件 + VLM 总结的真实模型链路。
    result = {
        "identify_brief": "时间记忆分析(桩)：已收到视频与语音输入，尚未接入真实模型",
        "navigation_summary": {
            "persons": [], "topics": [], "spaces": [],
            "key_moments": [], "suggested_questions": [],
        },
        "key_frames": [],
        "events": [],
        "faces": [],
    }
    log.info("时间记忆分析(桩)完成 job=%s memory=%s", job_id, memory_id)
    await send_callback(callback_url, job_id, memory_id, "succeeded", result, session_id=session_id)
