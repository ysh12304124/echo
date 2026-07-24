#!/usr/bin/env python3
"""Run FastGS training from a validated COLMAP scene."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from plyfile import PlyData

from colmap_model_io import validate_colmap_model
from pipeline_stage import append_event, run_stage_command, utc_now, write_stage_status


def validate_fastgs_scene(scene_dir: Path) -> None:
    if not (scene_dir / "images").is_dir():
        raise ValueError("FastGS scene is missing images directory: %s" % scene_dir)
    validate_colmap_model(scene_dir / "sparse" / "0")


def build_fastgs_commands(
    scene_dir: Path,
    model_dir: Path,
    fastgs_dir: Path,
    iterations: int,
    python_executable: str = "python",
    conda_executable: Optional[str] = None,
    conda_env: Optional[str] = None,
) -> list[list[str]]:
    prefix: list[str] = []
    if conda_executable and conda_env:
        prefix = [conda_executable, "run", "--no-capture-output", "-n", conda_env]
    return [[
        *prefix, python_executable, str(fastgs_dir / "train.py"),
        "-s", str(scene_dir), "-m", str(model_dir), "--images", "images",
        "--iterations", str(iterations), "--save_iterations", str(iterations),
        "--checkpoint_iterations", str(iterations),
    ]]


def find_trained_ply(model_dir: Path, iterations: int) -> Path:
    path = model_dir / "point_cloud" / ("iteration_%d" % iterations) / "point_cloud.ply"
    if not path.is_file():
        raise ValueError("FastGS PLY output does not exist: %s" % path)
    if path.stat().st_size <= 0:
        raise ValueError("FastGS PLY output is empty: %s" % path)
    try:
        ply = PlyData.read(str(path))
        vertex = ply["vertex"]
        if vertex is None or not {"x", "y", "z"}.issubset(vertex.data.dtype.names or ()):
            raise ValueError("FastGS PLY is missing x/y/z vertex properties")
        if len(vertex.data) == 0:
            raise ValueError("FastGS PLY has no vertices")
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError("FastGS PLY is malformed: %s" % path) from exc
    return path


def run_fastgs_stage(args: argparse.Namespace) -> int:
    job_dir = Path(args.job_dir).resolve()
    scene_dir = job_dir / "colmap_gravity_aligned"
    model_dir = job_dir / "fastgs_model"
    stage_dir = job_dir / "stages" / "fastgs"
    status_path = stage_dir / "status.json"
    events_path = job_dir / "events.jsonl"
    job_id = args.job_id or job_dir.name
    started_at = utc_now()
    write_stage_status(status_path, {"version": 1, "job_id": job_id, "stage": "fastgs", "status": "running", "started_at": started_at, "finished_at": None, "error_code": None, "message": "FastGS training is running.", "warnings": []})
    try:
        validate_fastgs_scene(scene_dir)
        if model_dir.exists():
            shutil.rmtree(model_dir)
        model_dir.mkdir(parents=True)
        commands = build_fastgs_commands(scene_dir, model_dir, Path(args.fastgs_dir).resolve(), args.iterations, args.python_executable, args.conda_executable, args.conda_env)
        environment = {"QT_QPA_PLATFORM": "offscreen"}
        if args.cuda_lib_dir:
            environment["LD_LIBRARY_PATH"] = args.cuda_lib_dir + ":" + os.environ.get("LD_LIBRARY_PATH", "")
        for index, command in enumerate(commands):
            code = run_stage_command(command, scene_dir, stage_dir / ("stdout_%d.log" % index), stage_dir / ("stderr_%d.log" % index), args.timeout_seconds, environment)
            if code != 0:
                raise RuntimeError("FastGS command %d exited with code %d" % (index, code))
        ply_path = find_trained_ply(model_dir, args.iterations)
        payload = {"version": 1, "job_id": job_id, "stage": "fastgs", "status": "completed", "started_at": started_at, "finished_at": utc_now(), "error_code": None, "message": "FastGS training completed.", "input": {"scene_dir": str(scene_dir)}, "output": {"model_dir": str(model_dir), "ply_path": str(ply_path)}, "metrics": {"iterations": args.iterations, "ply_size_bytes": ply_path.stat().st_size}, "warnings": []}
        write_stage_status(status_path, payload)
        append_event(events_path, {"timestamp": payload["finished_at"], "job_id": job_id, "stage": "fastgs", "status": "completed", "ply_path": str(ply_path)})
        return 0
    except Exception as exc:
        payload = {"version": 1, "job_id": job_id, "stage": "fastgs", "status": "failed", "started_at": started_at, "finished_at": utc_now(), "error_code": "FASTGS_STAGE_ERROR", "message": str(exc), "warnings": []}
        write_stage_status(status_path, payload)
        append_event(events_path, {"timestamp": payload["finished_at"], "job_id": job_id, "stage": "fastgs", "status": "failed", "error_code": payload["error_code"], "message": str(exc)})
        print("FastGS stage failed: %s" % exc, file=sys.stderr)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--fastgs-dir", required=True)
    parser.add_argument("--job-id")
    parser.add_argument("--iterations", type=int, default=30000)
    parser.add_argument("--python-executable", default="python")
    parser.add_argument("--conda-executable", default=None)
    parser.add_argument("--conda-env", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=1800)
    parser.add_argument("--cuda-lib-dir", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_fastgs_stage(parse_args()))
