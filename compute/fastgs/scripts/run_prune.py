#!/usr/bin/env python3
"""Run mandatory post-training Gaussian pruning before export."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from plyfile import PlyData

from pipeline_stage import append_event, run_stage_command, utc_now, write_stage_status


def build_prune_command(
    scene_dir: Path,
    model_dir: Path,
    fastgs_dir: Path,
    iterations: int,
    max_prune_ratio: float = 0.01,
    finetune_iterations: int = 800,
    evaluate_psnr: bool = True,
    python_executable: str = "python",
    conda_executable: Optional[str] = None,
    conda_env: Optional[str] = None,
    output_name: str = "geometric_pruned",
) -> list[str]:
    if finetune_iterations <= 0:
        raise ValueError("post-prune finetuning must use a positive iteration count")
    if not 0.0 <= max_prune_ratio <= 0.03:
        raise ValueError("max_prune_ratio must be in [0, 0.03]")
    prefix: list[str] = []
    if conda_executable and conda_env:
        prefix = [conda_executable, "run", "--no-capture-output", "-n", conda_env]
    command = [
        *prefix, python_executable, str(fastgs_dir / "prune_gaussians.py"),
        "-s", str(scene_dir), "-m", str(model_dir),
        "--iteration", str(iterations), "--output_name", output_name,
        "--max_prune_ratio", str(max_prune_ratio),
        "--finetune_iterations", str(finetune_iterations),
    ]
    if evaluate_psnr:
        command.append("--evaluate_psnr")
    return command


def find_pruned_outputs(model_dir: Path, iterations: int, output_name: str = "geometric_pruned") -> dict[str, Path]:
    root = model_dir / output_name
    paths = {
        "root": root,
        "ply": root / "point_cloud" / ("iteration_%d" % iterations) / "point_cloud.ply",
        "checkpoint": root / ("chkpnt_geometric_pruned_%d.pth" % iterations),
        "stats": root / "prune_stats.json",
    }
    missing = [str(path) for key, path in paths.items() if key == "root" and not path.is_dir() or key != "root" and (not path.is_file() or path.stat().st_size <= 0)]
    if missing:
        raise ValueError("pruned FastGS outputs are missing or empty: %s" % ", ".join(missing))
    try:
        vertex = PlyData.read(str(paths["ply"]))["vertex"]
        if len(vertex.data) == 0 or not {"x", "y", "z"}.issubset(vertex.data.dtype.names or ()):
            raise ValueError("pruned PLY has no usable vertices")
        stats = json.loads(paths["stats"].read_text(encoding="utf-8"))
        if stats.get("gaussians_after", 0) <= 0:
            raise ValueError("pruned statistics report no Gaussians")
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("pruned FastGS outputs are malformed") from exc
    return paths


def run_prune_stage(args: argparse.Namespace) -> int:
    job_dir = Path(args.job_dir).resolve()
    model_dir = job_dir / "fastgs_model"
    scene_dir = job_dir / "colmap_gravity_aligned"
    stage_dir = job_dir / "stages" / "prune"
    status_path = stage_dir / "status.json"
    events_path = job_dir / "events.jsonl"
    job_id = args.job_id or job_dir.name
    started_at = utc_now()
    write_stage_status(status_path, {
        "version": 1, "job_id": job_id, "stage": "prune", "status": "running",
        "started_at": started_at, "finished_at": None, "error_code": None,
        "message": "Mandatory Gaussian pruning and finetuning is running.", "warnings": [],
    })
    try:
        command = build_prune_command(
            scene_dir, model_dir, Path(args.fastgs_dir).resolve(), args.iterations,
            args.max_prune_ratio, args.finetune_iterations, args.evaluate_psnr,
            args.python_executable, args.conda_executable, args.conda_env,
        )
        environment = {"QT_QPA_PLATFORM": "offscreen"}
        if args.cuda_lib_dir:
            environment["LD_LIBRARY_PATH"] = args.cuda_lib_dir + ":" + os.environ.get("LD_LIBRARY_PATH", "")
        code = run_stage_command(
            command, scene_dir, stage_dir / "stdout.log", stage_dir / "stderr.log",
            args.timeout_seconds, environment,
        )
        if code != 0:
            raise RuntimeError("prune command exited with code %d" % code)
        outputs = find_pruned_outputs(model_dir, args.iterations)
        stats = json.loads(outputs["stats"].read_text(encoding="utf-8"))
        payload = {
            "version": 1, "job_id": job_id, "stage": "prune", "status": "completed",
            "started_at": started_at, "finished_at": utc_now(), "error_code": None,
            "message": "Gaussian pruning and finetuning completed.",
            "output": {key: str(value) for key, value in outputs.items()},
            "metrics": {key: stats.get(key) for key in (
                "gaussians_before", "gaussians_after", "pruned_count", "pruned_ratio",
                "pruned_redundant", "pruned_floater", "psnr_delta",
            )},
            "warnings": [],
        }
        write_stage_status(status_path, payload)
        append_event(events_path, {"timestamp": payload["finished_at"], "job_id": job_id, "stage": "prune", "status": "completed", "ply_path": str(outputs["ply"])})
        return 0
    except Exception as exc:
        payload = {
            "version": 1, "job_id": job_id, "stage": "prune", "status": "failed",
            "started_at": started_at, "finished_at": utc_now(), "error_code": "PRUNE_STAGE_ERROR",
            "message": str(exc), "warnings": [],
        }
        write_stage_status(status_path, payload)
        append_event(events_path, {"timestamp": payload["finished_at"], "job_id": job_id, "stage": "prune", "status": "failed", "error_code": payload["error_code"], "message": str(exc)})
        print("prune stage failed: %s" % exc, file=sys.stderr)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--fastgs-dir", required=True)
    parser.add_argument("--job-id")
    parser.add_argument("--iterations", type=int, default=30000)
    parser.add_argument("--max-prune-ratio", type=float, default=0.01)
    parser.add_argument("--finetune-iterations", type=int, default=800)
    parser.add_argument("--evaluate-psnr", action="store_true", default=True)
    parser.add_argument("--python-executable", default="python")
    parser.add_argument("--conda-executable", default=None)
    parser.add_argument("--conda-env", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=1800)
    parser.add_argument("--cuda-lib-dir", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_prune_stage(parse_args()))
