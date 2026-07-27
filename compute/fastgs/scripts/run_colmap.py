#!/usr/bin/env python3
"""Run the COLMAP stage and enforce the registration-rate contract."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from colmap_model_io import ModelMetrics, read_images_binary, validate_colmap_model
from pipeline_stage import (
    append_event,
    run_stage_command,
    utc_now,
    write_stage_status,
)


MINIMUM_REGISTRATION_RATIO = 0.8
JPEG_SUFFIXES = {".jpg", ".jpeg"}


@dataclass(frozen=True)
class RegistrationMetrics:
    input_image_count: int
    registered_image_count: int
    registration_ratio: float
    unregistered_images: list[str]
    model: ModelMetrics
    status: str
    error_code: Optional[str] = None


def count_input_images(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        raise ValueError("input image directory does not exist: %s" % input_dir)
    images = sorted(
        path for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in JPEG_SUFFIXES
    )
    if not images:
        raise ValueError("input image directory contains no JPEG images: %s" % input_dir)
    return images


def inspect_colmap_registration(
    model_dir: Path,
    input_image_names: list[str],
) -> RegistrationMetrics:
    model = validate_colmap_model(model_dir)
    registered = read_images_binary(model_dir / "images.bin")
    registered_names = {image.name for image in registered.values()}
    unregistered = [name for name in input_image_names if name not in registered_names]
    input_count = len(input_image_names)
    registered_count = len(registered_names)
    ratio = registered_count / input_count if input_count else 0.0
    if ratio < MINIMUM_REGISTRATION_RATIO:
        status = "failed"
        error_code = "LOW_REGISTRATION_RATIO"
    else:
        status = "completed" if not unregistered else "completed_with_warnings"
        error_code = None
    return RegistrationMetrics(
        input_image_count=input_count,
        registered_image_count=registered_count,
        registration_ratio=ratio,
        unregistered_images=unregistered,
        model=model,
        status=status,
        error_code=error_code,
    )


def build_colmap_command(
    input_dir: Path,
    output_dir: Path,
    fastgs_dir: Path,
    colmap_executable: str,
    python_executable: str = "python",
    conda_executable: Optional[str] = None,
    conda_env: Optional[str] = None,
    feature_gpu: bool = False,
    matching_gpu: bool = True,
    mapper_gpu: bool = True,
    colmap_new_api: bool = True,
    max_num_features: int = 8192,
    sequential: bool = True,
) -> list[str]:
    command = []
    if conda_executable and conda_env:
        command.extend([conda_executable, "run", "--no-capture-output", "-n", conda_env])
    command.extend([
        python_executable,
        str(fastgs_dir / "convert.py"),
        "--source_path", str(output_dir),
        "--camera", "OPENCV",
        "--colmap_executable", colmap_executable,
        "--max_num_features", str(max_num_features),
    ])
    if sequential:
        command.append("--sequential")
    if colmap_new_api:
        command.append("--colmap_new_api")
    if not feature_gpu:
        command.append("--no_gpu")
    if matching_gpu:
        command.append("--matching_gpu")
    if mapper_gpu:
        command.append("--mapper_use_gpu")
    return command


def _copy_input_images(input_dir: Path, output_dir: Path) -> None:
    destination = output_dir / "input"
    destination.mkdir(parents=True, exist_ok=True)
    for source in count_input_images(input_dir):
        target = destination / source.name
        if target.exists():
            target.unlink()
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)


def run_colmap_stage(args: argparse.Namespace) -> int:
    job_dir = Path(args.job_dir).resolve()
    input_dir = job_dir / "input"
    output_dir = job_dir / "colmap_raw"
    stage_dir = job_dir / "stages" / "colmap"
    status_path = stage_dir / "status.json"
    events_path = job_dir / "events.jsonl"
    job_id = args.job_id or job_dir.name
    started_at = utc_now()
    try:
        images = count_input_images(input_dir)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        _copy_input_images(input_dir, output_dir)
        write_stage_status(status_path, {
            "version": 1, "job_id": job_id, "stage": "colmap", "status": "running",
            "started_at": started_at, "finished_at": None, "error_code": None,
            "message": "COLMAP is running.", "warnings": [],
        })
        append_event(events_path, {"timestamp": started_at, "job_id": job_id, "stage": "colmap", "status": "running"})
        command = build_colmap_command(
            input_dir=input_dir,
            output_dir=output_dir,
            fastgs_dir=Path(args.fastgs_dir).resolve(),
            colmap_executable=args.colmap_executable,
            python_executable=args.python_executable,
            conda_executable=args.conda_executable,
            conda_env=args.conda_env,
            feature_gpu=args.feature_gpu,
            matching_gpu=args.matching_gpu,
            mapper_gpu=args.mapper_gpu,
            colmap_new_api=args.colmap_new_api,
            max_num_features=args.max_num_features,
            sequential=args.sequential,
        )
        code = run_stage_command(
            command,
            output_dir,
            stage_dir / "stdout.log",
            stage_dir / "stderr.log",
            args.timeout_seconds,
            environment={
                "QT_QPA_PLATFORM": "offscreen",
                "LD_LIBRARY_PATH": (
                    "%s:%s" % (args.cuda_lib_dir, os.environ.get("LD_LIBRARY_PATH", ""))
                    if args.cuda_lib_dir else os.environ.get("LD_LIBRARY_PATH", "")
                ),
            },
        )
        if code != 0:
            raise RuntimeError("COLMAP command exited with code %d" % code)
        model_dir = output_dir / "sparse" / "0"
        metrics = inspect_colmap_registration(model_dir, [path.name for path in images])
        warnings = []
        if metrics.unregistered_images:
            warnings.append("%d images were not registered by COLMAP." % len(metrics.unregistered_images))
        status = metrics.status
        message = "Registered %d of %d input images." % (
            metrics.registered_image_count, metrics.input_image_count
        )
        payload = {
            "version": 1, "job_id": job_id, "stage": "colmap", "status": status,
            "started_at": started_at, "finished_at": utc_now(),
            "error_code": metrics.error_code, "message": message,
            "input": {"image_dir": str(input_dir)},
            "output": {"colmap_dir": str(output_dir)},
            "metrics": {**asdict(metrics.model), "input_image_count": metrics.input_image_count,
                        "registered_image_count": metrics.registered_image_count,
                        "registration_ratio": metrics.registration_ratio},
            "unregistered_images": metrics.unregistered_images,
            "warnings": warnings,
        }
        write_stage_status(status_path, payload)
        append_event(events_path, {"timestamp": payload["finished_at"], "job_id": job_id, "stage": "colmap", "status": status, "metrics": payload["metrics"]})
        return 0 if status != "failed" else 1
    except Exception as exc:
        payload = {
            "version": 1, "job_id": job_id, "stage": "colmap", "status": "failed",
            "started_at": started_at, "finished_at": utc_now(),
            "error_code": getattr(exc, "error_code", "COLMAP_STAGE_ERROR"),
            "message": str(exc), "warnings": [],
        }
        write_stage_status(status_path, payload)
        append_event(events_path, {"timestamp": payload["finished_at"], "job_id": job_id, "stage": "colmap", "status": "failed", "error_code": payload["error_code"], "message": str(exc)})
        print("COLMAP stage failed: %s" % exc, file=sys.stderr)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--fastgs-dir", required=True)
    parser.add_argument("--job-id")
    parser.add_argument("--colmap-executable", default=os.getenv("FASTGS_COLMAP_EXECUTABLE", "/home/asus/opt/colmap-cuda-ceres/bin/colmap"))
    parser.add_argument("--python-executable", default="python")
    parser.add_argument("--conda-executable", default="conda")
    parser.add_argument("--conda-env", default="fastgs")
    parser.add_argument("--timeout-seconds", type=float, default=1800)
    parser.add_argument("--max-num-features", type=int, default=8192)
    parser.add_argument("--feature-gpu", action="store_true", default=os.getenv("FASTGS_FEATURE_USE_GPU", "0") == "1")
    parser.add_argument("--matching-gpu", action="store_true", default=os.getenv("FASTGS_MATCHING_USE_GPU", "1") == "1")
    parser.add_argument("--mapper-gpu", action="store_true", default=os.getenv("FASTGS_MAPPER_USE_GPU", "1") == "1")
    parser.add_argument("--colmap-new-api", action="store_true", default=os.getenv("FASTGS_COLMAP_NEW_API", "1") == "1")
    parser.add_argument("--sequential", action="store_true", default=True)
    parser.add_argument("--cuda-lib-dir", default=os.getenv("FASTGS_CUDA_LIB_DIR", "/usr/local/cuda-12.8/lib64"))
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_colmap_stage(parse_args()))
