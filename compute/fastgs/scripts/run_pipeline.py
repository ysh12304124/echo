#!/usr/bin/env python3
"""Orchestrate the four reconstruction stages with fail-fast semantics."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from colmap_model_io import validate_colmap_model
from pipeline_stage import append_event, read_stage_status, utc_now
from run_fastgs import find_trained_ply


STAGES = ("colmap", "alignment", "fastgs", "prune", "export")


def stage_command(stage: str, args: argparse.Namespace) -> list[str]:
    root = Path(__file__).resolve().parent
    common = [sys.executable, str(root / {
        "colmap": "run_colmap.py",
            "alignment": "align_colmap.py",
            "fastgs": "run_fastgs.py",
            "prune": "run_prune.py",
            "export": "export_outputs.py",
    }[stage]), "--job-dir", str(Path(args.job_dir).resolve())]
    if args.job_id:
        common += ["--job-id", args.job_id]
    if stage in {"colmap", "fastgs", "prune"}:
        common += ["--fastgs-dir", str(Path(args.fastgs_dir).resolve())]
    if stage == "colmap":
        common += [
            "--timeout-seconds", str(args.timeout_seconds),
            "--colmap-executable", getattr(args, "colmap_executable", "/home/asus/opt/colmap-cuda-ceres/bin/colmap"),
            "--python-executable", getattr(args, "python_executable", "python"),
            "--max-num-features", str(getattr(args, "max_num_features", 8192)),
        ]
        if getattr(args, "conda_executable", None) and getattr(args, "conda_env", None):
            common += ["--conda-executable", args.conda_executable, "--conda-env", args.conda_env]
        if getattr(args, "feature_gpu", False):
            common.append("--feature-gpu")
        if getattr(args, "matching_gpu", True):
            common.append("--matching-gpu")
        if getattr(args, "mapper_gpu", True):
            common.append("--mapper-gpu")
        if getattr(args, "cuda_lib_dir", None):
            common += ["--cuda-lib-dir", args.cuda_lib_dir]
    elif stage == "alignment":
        if args.allow_alignment_fallback:
            common.append("--allow-alignment-fallback")
    elif stage == "fastgs":
        common += [
            "--iterations", str(args.iterations),
            "--timeout-seconds", str(args.timeout_seconds),
            "--python-executable", getattr(args, "python_executable", "python"),
        ]
        if getattr(args, "conda_executable", None) and getattr(args, "conda_env", None):
            common += ["--conda-executable", args.conda_executable, "--conda-env", args.conda_env]
        if getattr(args, "cuda_lib_dir", None):
            common += ["--cuda-lib-dir", args.cuda_lib_dir]
    elif stage == "prune":
        common += [
            "--iterations", str(args.iterations),
                "--max-prune-ratio", str(getattr(args, "prune_max_ratio", 0.01)),
                "--finetune-iterations", str(getattr(args, "prune_finetune_iterations", 800)),
            "--timeout-seconds", str(args.timeout_seconds),
            "--python-executable", getattr(args, "python_executable", "python"),
        ]
        if getattr(args, "prune_evaluate_psnr", True):
            common.append("--evaluate-psnr")
        if getattr(args, "conda_executable", None) and getattr(args, "conda_env", None):
            common += ["--conda-executable", args.conda_executable, "--conda-env", args.conda_env]
        if getattr(args, "cuda_lib_dir", None):
            common += ["--cuda-lib-dir", args.cuda_lib_dir]
    elif stage == "export":
        common += ["--iterations", str(args.iterations)]
    return common


def _result_path(job_dir: Path) -> Path:
    return job_dir / "result.json"


def _write_failed_result(job_dir: Path, stage: str, status: dict) -> None:
    payload = {
        "version": 1,
        "status": "failed",
        "stage": stage,
        "finished_at": utc_now(),
        "error_code": status.get("error_code"),
        "error": status.get("message"),
    }
    _result_path(job_dir).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_resume_point(job_dir: Path, resume_from: str, iterations: int) -> None:
    if resume_from == "colmap":
        return
    colmap_status = read_stage_status(job_dir / "stages" / "colmap" / "status.json")
    if colmap_status["status"] not in {"completed", "completed_with_warnings"}:
        raise ValueError("cannot resume from %s: COLMAP stage is not complete" % resume_from)
    if resume_from == "alignment":
        validate_colmap_model(job_dir / "colmap_raw" / "sparse" / "0")
        return
    alignment_status = read_stage_status(job_dir / "stages" / "alignment" / "status.json")
    if alignment_status["status"] not in {"completed", "completed_with_warnings"}:
        raise ValueError("cannot resume from %s: alignment stage is not complete" % resume_from)
    if resume_from == "fastgs":
        validate_colmap_model(job_dir / "colmap_gravity_aligned" / "sparse" / "0")
        return
    fastgs_status = read_stage_status(job_dir / "stages" / "fastgs" / "status.json")
    if fastgs_status["status"] not in {"completed", "completed_with_warnings"}:
        raise ValueError("cannot resume from export: FastGS stage is not complete")
    if resume_from == "prune":
        find_trained_ply(job_dir / "fastgs_model", iterations)
        return
    prune_status = read_stage_status(job_dir / "stages" / "prune" / "status.json")
    if prune_status["status"] not in {"completed", "completed_with_warnings"}:
        raise ValueError("cannot resume from export: prune stage is not complete")
    from run_prune import find_pruned_outputs
    find_pruned_outputs(job_dir / "fastgs_model", iterations)


def run_pipeline(args: argparse.Namespace) -> int:
    job_dir = Path(args.job_dir).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    try:
        _validate_resume_point(job_dir, args.resume_from, args.iterations) if args.resume_from else None
    except Exception as exc:
        _write_failed_result(job_dir, args.resume_from or "pipeline", {"error_code": "INVALID_RESUME_POINT", "message": str(exc)})
        return 1
    start_index = STAGES.index(args.resume_from) if args.resume_from else 0
    for stage in STAGES[start_index:]:
        command = stage_command(stage, args)
        append_event(job_dir / "events.jsonl", {"timestamp": utc_now(), "job_id": args.job_id or job_dir.name, "stage": stage, "status": "started", "command": command})
        completed = subprocess.run(command, cwd=str(job_dir), check=False)
        status_path = job_dir / "stages" / stage / "status.json"
        try:
            status = read_stage_status(status_path)
        except Exception as exc:
            status = {"status": "failed", "error_code": "MISSING_STAGE_STATUS", "message": str(exc)}
        if completed.returncode != 0 or status["status"] == "failed":
            _write_failed_result(job_dir, stage, status)
            append_event(job_dir / "events.jsonl", {"timestamp": utc_now(), "job_id": args.job_id or job_dir.name, "stage": stage, "status": "failed", "error_code": status.get("error_code"), "message": status.get("message")})
            return 1
        if status["status"] not in {"completed", "completed_with_warnings"}:
            _write_failed_result(job_dir, stage, {"error_code": "INVALID_STAGE_STATUS", "message": "stage did not complete: %s" % status["status"]})
            return 1
    output_result = job_dir / "outputs" / "result.json"
    if output_result.is_file():
        payload = json.loads(output_result.read_text(encoding="utf-8"))
        payload["pipeline_status"] = "completed"
        _result_path(job_dir).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--fastgs-dir", required=True)
    parser.add_argument("--job-id")
    parser.add_argument("--iterations", type=int, default=30000)
    parser.add_argument("--timeout-seconds", type=float, default=1800)
    parser.add_argument("--allow-alignment-fallback", action="store_true")
    parser.add_argument("--resume-from", choices=STAGES)
    parser.add_argument("--conda-executable", default="conda")
    parser.add_argument("--conda-env", default="fastgs")
    parser.add_argument("--python-executable", default="python")
    parser.add_argument("--colmap-executable", default="/home/asus/opt/colmap-cuda-ceres/bin/colmap")
    parser.add_argument("--max-num-features", type=int, default=8192)
    parser.add_argument("--feature-gpu", action="store_true")
    parser.add_argument("--matching-gpu", action="store_true", default=True)
    parser.add_argument("--mapper-gpu", action="store_true", default=True)
    parser.add_argument("--cuda-lib-dir", default="/usr/local/cuda-12.8/lib64")
    parser.add_argument("--prune-max-ratio", type=float, default=0.01)
    parser.add_argument("--prune-finetune-iterations", type=int, default=800)
    parser.add_argument("--prune-evaluate-psnr", action="store_true", default=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_pipeline(parse_args()))
