"""时间记忆分析：本期桩实现。读取输入、记录日志、回填占位 result 并回调。

真实实现(阶段四)：视频抽帧 -> 人脸检测/识别(人脸识别模型) + 关键帧/事件识别(YOLO) ->
关键帧+事件送视觉大模型(VLM)总结 -> 输出 identify_brief/navigation_summary/key_frames/
events/faces。字段需与实现方对齐后钉死，详见 docs/protocols/compute-service.md「接口①B / 接口②B」。
"""

from __future__ import annotations

from typing import Any

from app.callback import send_callback
from app.logging_setup import get_session_logger
from pathlib import Path
import asyncio, os
from functools import partial


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


    if video_path and Path(video_path).is_file():
        out_dir = Path(__file__).resolve().parent / "outputs" / "emotion_keyframe_output"
        echo_root = Path(__file__).resolve().parent.parent.parent.parent  # → D:\echo
        face_db_path = str(echo_root / "backend" / "data" / "faceDataBase")
        os.makedirs(str(out_dir), exist_ok=True)
        from deepface import DeepFace
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(
                DeepFace.stream,
                db_path=face_db_path,
                source=video_path,
                detector_backend="scrfd",
                anti_spoofing=True,
                enable_face_analysis=True,
                time_threshold=0,
                frame_threshold=1,
                keyframe_output_dir=str(out_dir),
            ),
        )
        log.info("人脸分析完成 job=%s", job_id)
    else:
        log.warning("video_path 无效 job=%s", job_id)
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
