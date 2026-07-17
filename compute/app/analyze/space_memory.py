"""空间记忆分析：本期桩实现。读取输入、记录日志、回填占位 result 并回调。

真实实现(阶段四)：视频抽帧 + IMU -> 重建/点云，产出模型文件直接写共享磁盘约定路径
(如 sessions/{sid}/space/model.glb)，回调 JSON 只回文件路径。当前正式流程仍走
backend 现有的 RemoteReconstructionService，不受本桩实现影响。
详见 docs/protocols/compute-service.md「接口①C / 接口②C」。
"""

from __future__ import annotations

from typing import Any

from app.callback import send_callback
from app.logging_setup import get_session_logger


async def run_space_analysis(
    job_id: str,
    memory_id: str,
    session_id: str,
    inputs: dict[str, Any],
    callback_url: str,
) -> None:
    log = get_session_logger("analyze.space", session_id)
    video_path = inputs.get("video_path")
    imu_path = inputs.get("imu_path")
    log.info(
        "开始空间记忆分析(桩) job=%s memory=%s video=%s imu=%s",
        job_id, memory_id, video_path, imu_path,
    )

    # TODO(阶段四): 接入抽帧 + IMU 重建/点云的真实模型链路，产出物写共享盘。
    result = {
        "model_url": None,
        "model_format": None,
        "quality": "good",
        "loop_angle": None,
        "scene_summary": "空间记忆分析(桩)：已收到视频与 IMU 输入，尚未接入真实模型",
        "identify_brief": "空间记忆分析(桩)完成",
        "anchors": [],
    }
    log.info("空间记忆分析(桩)完成 job=%s memory=%s", job_id, memory_id)
    await send_callback(callback_url, job_id, memory_id, "succeeded", result, session_id=session_id)
