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
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.callback import send_callback
from app.analyze.imu_manifest import build_imu_manifest
from app.logging_setup import get_session_logger
from app.settings import get_settings


JPEG_EXTS = {".jpg", ".jpeg"}
_STORAGE_TIME_ZONE = ZoneInfo("Asia/Shanghai")


def _log_pipeline_event(log, event: dict[str, Any]) -> None:
    """Mirror FastGS pipeline events into the Compute service log."""
    stage = str(event.get("stage") or "pipeline")
    status = str(event.get("status") or "unknown")
    timestamp = str(event.get("timestamp") or "-")
    metrics = event.get("metrics")
    details = f" metrics={json.dumps(metrics, ensure_ascii=False, sort_keys=True)}" if metrics else ""

    if status == "started":
        log.info("FastGS 阶段开始 stage=%s timestamp=%s%s", stage, timestamp, details)
    elif status in {"completed", "completed_with_warnings"}:
        log.info("FastGS 阶段完成 stage=%s timestamp=%s%s", stage, timestamp, details)
    elif status == "failed":
        log.warning(
            "FastGS 阶段失败 stage=%s timestamp=%s error_code=%s message=%s",
            stage,
            timestamp,
            event.get("error_code") or "-",
            event.get("message") or "-",
        )
    else:
        log.info("FastGS 阶段状态 stage=%s status=%s timestamp=%s%s", stage, status, timestamp, details)


def _mirror_pipeline_events(job_dir: Path, stop_event: threading.Event, log) -> None:
    """Tail FastGS events.jsonl while reconstruction is running."""
    events_path = job_dir / "events.jsonl"
    offset = 0
    while True:
        if events_path.is_file():
            with events_path.open("r", encoding="utf-8") as stream:
                stream.seek(offset)
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    if not line.endswith("\n"):
                        break
                    offset = stream.tell()
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        _log_pipeline_event(log, event)
        if stop_event.wait(0.25):
            break

    if events_path.is_file():
        with events_path.open("r", encoding="utf-8") as stream:
            stream.seek(offset)
            while True:
                line = stream.readline()
                if not line:
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    _log_pipeline_event(log, event)


def _mirror_fastgs_output(stream, log) -> None:
    for line in iter(stream.readline, ""):
        message = line.rstrip()
        if message:
            log.info("FastGS 输出 %s", message)


def _space_blob_directory_name(memory_id: str, captured_at_ms: int) -> str:
    """Return a human-readable, collision-resistant blob directory name."""
    if captured_at_ms <= 0:
        return memory_id

    captured_at = datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc)
    timestamp = captured_at.astimezone(_STORAGE_TIME_ZONE).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{memory_id.split('-', 1)[0]}"


def _probe_video_duration(video_path: str) -> float | None:
    """Read the encoded video duration, falling back when container metadata is absent."""
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return None
        duration = float(proc.stdout.strip())
        return duration if duration > 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _extract_frames(video_path: str, out_dir: Path, fps: int, log) -> int:
    """用 ffmpeg 从视频抽 JPEG 帧到 out_dir/frame_%06d.jpg，返回帧数。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "frame_%06d.jpg")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps={fps},transpose=2,scale=-2:1024", "-q:v", "2",
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
        # 允许没有 IMU manifest 时用视觉方式对齐（不做 gravity alignment，用 fallback）。
        "--allow-alignment-fallback",
    ]
    # apt 装的 colmap 3.7 通常无 CUDA，且不支持 --colmap_new_api。
    # 通过 FASTGS_* 环境变量控制内部脚本默认值。
    env_extra = {
        # 空间记忆场景下我们不用 CUDA colmap，即使 use_gpu=True 也要显式设 CUDA lib dir。
        "FASTGS_CUDA_LIB_DIR": "",  # 无自定义 CUDA lib，用系统默认 LD_LIBRARY_PATH
    }
    if not settings.fastgs_colmap_use_gpu:
        env_extra.update({
            "FASTGS_MAPPER_USE_GPU": "0",
            "FASTGS_MATCHING_USE_GPU": "0",
            "FASTGS_FEATURE_USE_GPU": "0",
            "FASTGS_COLMAP_NEW_API": "0",  # apt colmap 3.7 无新 API
        })

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
    event_stop = threading.Event()
    event_thread = threading.Thread(
        target=_mirror_pipeline_events,
        args=(job_dir, event_stop, log),
        name=f"fastgs-events-{job_id}",
        daemon=True,
    )
    event_thread.start()
    proc = subprocess.Popen(
        cmd,
        cwd=str(fastgs_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        errors="replace",
    )
    output_thread = threading.Thread(
        target=_mirror_fastgs_output,
        args=(proc.stdout, log),
        name=f"fastgs-output-{job_id}",
        daemon=True,
    )
    output_thread.start()
    timeout_seconds = settings.fastgs_timeout_seconds + 60
    try:
        while proc.poll() is None:
            if time.monotonic() - start > timeout_seconds:
                proc.kill()
                proc.wait()
                raise TimeoutError(f"FastGS 超时 ({timeout_seconds}s)")
            time.sleep(0.25)
        return_code = proc.wait()
    finally:
        event_stop.set()
        event_thread.join(timeout=2)
        output_thread.join(timeout=2)

    elapsed = time.monotonic() - start
    log.info("FastGS 结束 exit=%d 用时=%.1fs", return_code, elapsed)
    if return_code != 0:
        raise RuntimeError(f"FastGS 失败 exit={return_code}，详见 compute.log 和 {job_dir}")

    result_path = job_dir / "result.json"
    if not result_path.is_file():
        raise RuntimeError(f"FastGS 未产出 result.json: {result_path}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_to_blob(
    memory_id: str,
    job_result: dict,
    blob_root: Path,
    log,
    captured_at_ms: int = 0,
) -> dict:
    """把 PLY/poses/anchor 从 job_dir 拷贝到 blob: spaces/<timestamp>/models/。

    FastGS 新 run_pipeline.py 的 result.json 结构:
        outputs: {point_cloud, poses_txt, poses_json, anchor}
        anchor_method, registered_image_count 在顶层

    返回 dict，含 URL / anchor_data / sha256。
    """
    outputs = job_result.get("outputs") or {}
    ply_src_str = outputs.get("point_cloud")
    poses_src_str = outputs.get("poses_txt")
    anchor_src_str = outputs.get("anchor")
    if not (ply_src_str and poses_src_str and anchor_src_str):
        raise RuntimeError(f"result.json outputs 字段缺失: {outputs}")
    ply_src = Path(ply_src_str)
    poses_src = Path(poses_src_str)
    anchor_src = Path(anchor_src_str)
    for p in (ply_src, poses_src, anchor_src):
        if not p.is_file():
            raise RuntimeError(f"FastGS 产出缺失: {p}")

    blob_directory = _space_blob_directory_name(memory_id, captured_at_ms)
    dst_dir = blob_root / "spaces" / blob_directory / "models"
    dst_dir.mkdir(parents=True, exist_ok=True)
    ply_dst = dst_dir / "point_cloud.ply"
    poses_dst = dst_dir / "poses.txt"
    anchor_dst = dst_dir / "anchor.json"
    shutil.copy(ply_src, ply_dst)
    shutil.copy(poses_src, poses_dst)
    shutil.copy(anchor_src, anchor_dst)
    log.info("产物拷贝至 blob: %s", dst_dir)

    # backend 里 /api/v1/media/{key} 会读 blob_root/{key}
    base = f"/api/v1/media/spaces/{blob_directory}/models"
    anchor_data = json.loads(anchor_dst.read_text(encoding="utf-8"))
    return {
        "model_url": f"{base}/point_cloud.ply",
        "poses_url": f"{base}/poses.txt",
        "anchor_url": f"{base}/anchor.json",
        "poses_sha256": _sha256_of(poses_dst),
        "anchor_sha256": _sha256_of(anchor_dst),
        "anchor_data": anchor_data,
    }


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
    recording_started_at_ms = int(inputs.get("recording_started_at_ms") or 0)
    captured_at_ms = int(inputs.get("captured_at_ms") or 0)

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

        manifest_stats = build_imu_manifest(
            Path(inputs["imu_path"]) if inputs.get("imu_path") else None,
            job_dir / "input",
            settings.fastgs_extract_fps,
            recording_started_at_ms,
            job_dir / "imu_manifest.json",
            settings.imu_acceleration_type,
        )
        log.info("IMU manifest 完成: %s", manifest_stats)

        fastgs_result = _run_fastgs(job_dir, job_id, settings, log)
        actual_duration_sec = _probe_video_duration(video_path) or recording_duration_sec
        blob_root = Path(settings.blob_storage_path).resolve()
        copy = _copy_to_blob(
            memory_id,
            fastgs_result,
            blob_root,
            log,
            captured_at_ms=captured_at_ms,
        )
        log.info("FastGS 产物已写入 Blob model_url=%s poses_url=%s anchor_url=%s", copy["model_url"], copy["poses_url"], copy["anchor_url"])

        anchor_data = copy["anchor_data"]
        anchor_pos = anchor_data.get("position") or {}
        # FastGS run_pipeline.py 只输出 registered_image_count；老脚本用 pose_count，两个都兼容。
        pose_count = int(
            fastgs_result.get("registered_image_count")
            or fastgs_result.get("pose_count")
            or 0
        )
        anchor_method = (
            fastgs_result.get("anchor_method")
            or anchor_data.get("method")
        )
        return {
            "model_url": copy["model_url"],
            "model_format": "ply",
            "quality": "good",
            "loop_angle": None,
            "scene_summary": f"FastGS 完成 {pose_count} 帧，{frame_count} 张 JPEG",
            "identify_brief": f"空间记忆已重建（{pose_count} 帧位姿）",
            "alignment_method": fastgs_result.get("alignment_method", "colmap_world"),
            "alignment_residual_degrees": fastgs_result.get("alignment_residual_degrees"),
            "imu_manifest": manifest_stats,
            "poses_url": copy["poses_url"],
            "poses_sha256": copy["poses_sha256"],
            "pose_count": pose_count,
            "anchor_url": copy["anchor_url"],
            "anchor_sha256": copy["anchor_sha256"],
            "anchor": {
                "method": anchor_method,
                "position": {
                    "x": float(anchor_pos.get("x", 0.0)),
                    "y": float(anchor_pos.get("y", 0.0)),
                    "z": float(anchor_pos.get("z", 0.0)),
                },
            },
            "scene_type": scene_type,
            "recording_duration_sec": actual_duration_sec,
        }

    status = "succeeded"
    result: dict = {}
    try:
        result = await asyncio.to_thread(_run_sync)
    except Exception as exc:
        status = "failed"
        result = {"error": str(exc)[:1000]}
        log.exception("空间分析失败 job=%s memory=%s", job_id, memory_id)

    log.info("开始回传空间重建结果 job=%s memory=%s status=%s", job_id, memory_id, status)
    await send_callback(callback_url, job_id, memory_id, status, result, session_id=session_id)
    log.info("空间分析回调完成 job=%s status=%s", job_id, status)
