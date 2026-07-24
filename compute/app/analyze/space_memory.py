"""空间记忆分析：抽帧 → COLMAP → FastGS 3DGS 训练 → 拷贝到 blob 共享盘。

流程（对应 docs/protocols/compute-service.md「接口①C / 接口②C」）：
1. 拿 inputs["video_path"] 抽 15fps JPEG 帧到 job_dir/input/
2. 起 FastGS scripts/reconstruct_images.py 完成 COLMAP + 训练 + poses.txt + anchor.json 生成
3. 把 point_cloud.ply / poses.txt / anchor.json 复制到 blob: spaces/{memory_id}/models/
4. 回调 backend/internal/callback/space，把 model_url/poses_url/anchor 全部字段带回

FastGS 参数走 ComputeSettings，见 app/settings.py 里以 "fastgs_" 开头的字段。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from app.callback import send_callback
from app.logging_setup import get_session_logger
from app.settings import get_settings


JPEG_EXTS = {".jpg", ".jpeg"}


def _extract_frames(video_path: str, out_dir: Path, fps: int, log) -> int:
    """用 ffmpeg 从视频抽 JPEG 帧到 out_dir/frame_%06d.jpg，返回帧数。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%06d.jpg")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps={fps}", "-q:v", "2",
        pattern,
    ]
    log.info("ffmpeg 抽帧 cmd=%s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 抽帧失败: {proc.stderr[-500:]}")
    frames = sorted(p for p in out_dir.iterdir() if p.suffix.lower() in JPEG_EXTS)
    return len(frames)


def _run_fastgs(job_dir: Path, job_id: str, settings, log) -> dict:
    """跑 scripts/reconstruct_images.py，等它 EXIT 0；返回 result.json 内容。"""
    fastgs_root = Path(settings.fastgs_dir).resolve()
    script = fastgs_root / "scripts" / "reconstruct_images.py"
    if not script.is_file():
        raise RuntimeError(f"FastGS 脚本不存在: {script}")

    cmd = [
        settings.fastgs_python, str(script),
        "--job-dir", str(job_dir),
        "--fastgs-dir", str(fastgs_root),
        "--conda-env", settings.fastgs_conda_env,
        "--conda-executable", settings.fastgs_conda_executable,
        "--python-executable", settings.fastgs_python,
        "--colmap-executable", settings.fastgs_colmap_executable,
        "--iterations", str(settings.fastgs_train_iterations),
        "--max_num_features", str(settings.fastgs_max_num_features),
        "--timeout-seconds", str(settings.fastgs_timeout_seconds),
        "--job-id", job_id,
    ]
    # apt 装的 colmap 通常无 CUDA，需要显式关掉 mapper/matching 的 GPU 开关。
    env_extra = {}
    if not settings.fastgs_colmap_use_gpu:
        env_extra = {
            "FASTGS_MAPPER_USE_GPU": "0",
            "FASTGS_MATCHING_USE_GPU": "0",
            "FASTGS_FEATURE_USE_GPU": "0",
        }

    env = os.environ.copy()
    env.update(env_extra)
    # 提高文件描述符上限，避免 1000+ 帧训练时 "Too many open files"。
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft < 65536:
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(65536, hard), hard))
    except Exception:
        pass

    log.info("FastGS 启动 cmd=%s", " ".join(cmd[:6]) + " ...")
    start = time.monotonic()
    proc = subprocess.run(
        cmd, cwd=str(fastgs_root), env=env, capture_output=True, text=True,
        timeout=settings.fastgs_timeout_seconds + 60,
    )
    elapsed = time.monotonic() - start
    log.info("FastGS 结束 exit=%d 用时=%.1fs", proc.returncode, elapsed)
    if proc.returncode != 0:
        tail_out = proc.stdout[-500:] if proc.stdout else ""
        tail_err = proc.stderr[-500:] if proc.stderr else ""
        raise RuntimeError(
            f"FastGS 失败 exit={proc.returncode}\nstdout tail: {tail_out}\nstderr tail: {tail_err}"
        )

    result_path = job_dir / "result.json"
    if not result_path.is_file():
        raise RuntimeError(f"FastGS 未产出 result.json: {result_path}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def _copy_to_blob(
    memory_id: str,
    job_result: dict,
    blob_root: Path,
    log,
) -> tuple[str, str, str, dict]:
    """把 PLY/poses/anchor 从 job_dir 拷贝到 blob: spaces/{memory_id}/models/。

    返回 (model_url, poses_url, anchor_url, anchor_json_dict)。
    """
    ply_src = Path(job_result["ply_path"])
    poses_src = Path(job_result["poses_path"])
    anchor_src = Path(job_result["anchor_path"])
    for p in (ply_src, poses_src, anchor_src):
        if not p.is_file():
            raise RuntimeError(f"FastGS 产出缺失: {p}")

    dst_dir = blob_root / "spaces" / memory_id / "models"
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(ply_src, dst_dir / "point_cloud.ply")
    shutil.copy(poses_src, dst_dir / "poses.txt")
    shutil.copy(anchor_src, dst_dir / "anchor.json")
    log.info("产物拷贝至 blob: %s", dst_dir)

    # backend 里 /api/v1/media/{key} 会读 blob_root/{key}
    base = f"/api/v1/media/spaces/{memory_id}/models"
    model_url = f"{base}/point_cloud.ply"
    poses_url = f"{base}/poses.txt"
    anchor_url = f"{base}/anchor.json"

    anchor_data = json.loads(anchor_src.read_text(encoding="utf-8"))
    return model_url, poses_url, anchor_url, anchor_data


async def run_space_analysis(
    job_id: str,
    memory_id: str,
    session_id: str,
    inputs: dict[str, Any],
    callback_url: str,
) -> None:
    """空间记忆分析入口。异常内部处理，回调状态区分 succeeded/failed。"""
    log = get_session_logger("analyze.space", session_id)
    settings = get_settings()
    video_path = inputs.get("video_path")
    scene_type = inputs.get("scene_type")
    recording_duration_sec = float(inputs.get("recording_duration_sec") or 0.0)

    log.info(
        "开始空间分析 job=%s memory=%s scene_type=%s video=%s duration=%.1fs",
        job_id, memory_id, scene_type, video_path, recording_duration_sec,
    )

    def _run_sync() -> dict:
        """在工作线程内跑抽帧 + FastGS（都是阻塞式 subprocess）。"""
        if not video_path or not Path(video_path).is_file():
            raise RuntimeError(f"video_path 不存在: {video_path}")

        work_root = Path(settings.fastgs_work_root)
        work_root.mkdir(parents=True, exist_ok=True)
        job_dir = work_root / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True)
        log.info("job_dir=%s", job_dir)

        frame_count = _extract_frames(
            video_path, job_dir / "input", settings.fastgs_extract_fps, log
        )
        log.info("抽帧完成 %d 张", frame_count)
        if frame_count < 3:
            raise RuntimeError(f"帧数不足 ({frame_count} < 3)，无法进行 COLMAP")

        fastgs_result = _run_fastgs(job_dir, job_id, settings, log)
        blob_root = Path(settings.blob_storage_path).resolve()
        model_url, poses_url, anchor_url, anchor_data = _copy_to_blob(
            memory_id, fastgs_result, blob_root, log
        )

        anchor_pos = anchor_data.get("position") or {}
        pose_count = int(fastgs_result.get("pose_count") or 0)
        return {
            "model_url": model_url,
            "model_format": "ply",
            "quality": "good",
            "loop_angle": None,
            "scene_summary": f"FastGS 完成 {pose_count} 帧，{frame_count} 张 JPEG",
            "identify_brief": f"空间记忆已重建（{pose_count} 帧位姿）",
            "poses_url": poses_url,
            "poses_sha256": fastgs_result.get("poses_sha256"),
            "pose_count": pose_count,
            "anchor_url": anchor_url,
            "anchor_sha256": fastgs_result.get("anchor_sha256"),
            "anchor": {
                "method": anchor_data.get("method"),
                "position": {
                    "x": float(anchor_pos.get("x", 0.0)),
                    "y": float(anchor_pos.get("y", 0.0)),
                    "z": float(anchor_pos.get("z", 0.0)),
                },
            },
            "scene_type": scene_type,
            "recording_duration_sec": recording_duration_sec,
        }

    status = "succeeded"
    result: dict = {}
    try:
        result = await asyncio.to_thread(_run_sync)
    except Exception as exc:
        status = "failed"
        result = {"error": str(exc)[:1000]}
        log.exception("空间分析失败 job=%s memory=%s", job_id, memory_id)

    await send_callback(callback_url, job_id, memory_id, status, result, session_id=session_id)
    log.info("空间分析回调完成 job=%s status=%s", job_id, status)
