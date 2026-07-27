#!/usr/bin/env python3
"""Run COLMAP conversion and FastGS training for an image-only job."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gravity_alignment import AlignmentResult, apply_gravity_alignment


JPEG_SUFFIXES = {".jpg", ".jpeg"}


@dataclass(frozen=True)
class Commands:
    colmap: list[str]
    train: list[str]
    environment: dict[str, str]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_input_dir(job_dir: Path, minimum_images: int = 3) -> list[Path]:
    input_dir = job_dir / "input"
    if not input_dir.is_dir():
        raise ValueError(f"input directory does not exist: {input_dir}")

    images = sorted(
        path for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in JPEG_SUFFIXES
    )
    if len(images) < minimum_images:
        raise ValueError(
            f"input directory must contain at least {minimum_images} JPEG images; "
            f"found {len(images)}"
        )
    return images


def build_commands(
    job_dir: Path,
    fastgs_dir: Path,
    conda_env: str,
    iterations: int,
    python_executable: str = "python",
    conda_executable: str = "conda",
    colmap_executable: str = "/home/asus/opt/colmap-cuda-ceres/bin/colmap",
    colmap_new_api: bool = True,
    mapper_use_gpu: bool = True,
    cuda_lib_dir: Optional[str] = "/usr/local/cuda-12.8/lib64",
    matching_use_gpu: bool = True,
    max_num_features: int = 8192,
    feature_use_gpu: bool = False,
) -> Commands:
    prefix = [conda_executable, "run", "--no-capture-output", "-n", conda_env]
    convert_script = fastgs_dir / "convert.py"
    train_script = fastgs_dir / "train.py"
    model_dir = job_dir / "model"
    common = [python_executable]
    return Commands(
        colmap=prefix + common + [
            str(convert_script),
            "--source_path", str(job_dir),
            "--sequential",
            "--camera", "OPENCV",
            "--colmap_executable", colmap_executable,
            "--max_num_features", str(max_num_features),
            *( ["--colmap_new_api"] if colmap_new_api else [] ),
            *( ["--no_gpu"] if not feature_use_gpu else [] ),
            *( ["--matching_gpu"] if matching_use_gpu else [] ),
            *( ["--mapper_use_gpu"] if mapper_use_gpu else [] ),
        ],
        environment={
            "LD_LIBRARY_PATH": (
                f"{cuda_lib_dir}:{os.environ.get('LD_LIBRARY_PATH', '')}"
                if cuda_lib_dir else os.environ.get("LD_LIBRARY_PATH", "")
            )
        },
        train=prefix + common + [
            str(train_script),
            "-s", str(job_dir),
            "-m", str(model_dir),
            "--images", "images",
            "--iterations", str(iterations),
            "--save_iterations", str(iterations),
            "--checkpoint_iterations", str(iterations),
        ],
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_output_ply(path: Path) -> Path:
    if not path.is_file():
        raise ValueError(f"PLY output does not exist: {path}")
    if path.stat().st_size <= 0:
        raise ValueError(f"PLY output is empty: {path}")
    return path


def poses_text_from_colmap_images(images: dict, image_names: list[str]) -> str:
    """Serialize registered COLMAP poses as row-major camera-to-world matrices."""
    return "\n".join(
        " ".join(f"{value:.15f}" for value in matrix.reshape(-1))
        for matrix in c2w_matrices_from_colmap_images(images, image_names)
    ) + "\n"


def c2w_matrices_from_colmap_images(images: dict, image_names: list[str]):
    import numpy as np

    by_name = {image.name: image for image in images.values()}
    missing = [name for name in image_names if name not in by_name]
    if missing:
        raise ValueError("COLMAP did not register images: " + ", ".join(missing))

    matrices = []
    for name in image_names:
        image = by_name[name]
        rotation_w2c = np.asarray(image.qvec2rotmat(), dtype=float)
        translation_w2c = np.asarray(image.tvec, dtype=float)
        rotation_c2w = rotation_w2c.T
        translation_c2w = -rotation_c2w @ translation_w2c
        matrix = np.eye(4, dtype=float)
        matrix[:3, :3] = rotation_c2w
        matrix[:3, 3] = translation_c2w
        matrices.append(matrix)
    return matrices


def write_colmap_poses(job_dir: Path, fastgs_dir: Path, image_names: list[str]) -> Path:
    """Read COLMAP binary extrinsics and write poses.txt in input image order."""
    if str(fastgs_dir) not in sys.path:
        sys.path.insert(0, str(fastgs_dir))
    from scene.colmap_loader import read_extrinsics_binary

    images_path = job_dir / "sparse" / "0" / "images.bin"
    poses_path = job_dir / "poses.txt"
    images = read_extrinsics_binary(str(images_path))
    poses_path.write_text(
        poses_text_from_colmap_images(images, image_names),
        encoding="utf-8",
    )
    return poses_path


def _solve_ray_intersection(poses):
    """Find the point nearest to camera-forward rays with Huber IRLS weights."""
    import numpy as np

    origins = np.asarray([pose[:3, 3] for pose in poses], dtype=float)
    directions = np.asarray([pose[:3, 2] for pose in poses], dtype=float)
    norms = np.linalg.norm(directions, axis=1)
    if len(poses) < 3 or np.any(norms <= 1e-9):
        return None
    directions = directions / norms[:, None]
    projectors = np.eye(3)[None, :, :] - directions[:, :, None] * directions[:, None, :]
    weights = np.ones(len(poses), dtype=float)
    anchor = None
    for _ in range(8):
        weighted = projectors * weights[:, None, None]
        matrix = weighted.sum(axis=0)
        vector = np.einsum("nij,nj->i", weighted, origins).astype(float)
        if np.linalg.matrix_rank(matrix, tol=1e-8) < 3:
            return None
        condition = np.linalg.cond(matrix)
        if not np.isfinite(condition) or condition > 1e8:
            return None
        try:
            candidate = np.linalg.solve(matrix, vector)
        except np.linalg.LinAlgError:
            return None
        residuals = np.linalg.norm(np.einsum("nij,nj->ni", projectors, candidate - origins), axis=1)
        scale = max(float(np.median(residuals)), 1e-6)
        weights = np.minimum(1.0, (1.5 * scale) / np.maximum(residuals, 1e-9))
        anchor = candidate
    if anchor is None or not np.all(np.isfinite(anchor)):
        return None
    return anchor


def _point_cloud_bbox_center(ply_path: Path):
    """Read x/y/z from an ASCII or scalar-property binary PLY."""
    import numpy as np

    with ply_path.open("rb") as stream:
        header = bytearray()
        while b"end_header\n" not in header and b"end_header\r\n" not in header:
            line = stream.readline()
            if not line:
                raise ValueError("PLY header is incomplete")
            header.extend(line)
        header_text = bytes(header).decode("ascii")
        data_offset = len(header)

        lines = [line.strip() for line in header_text.splitlines()]
        fmt = next((line.split()[1] for line in lines if line.startswith("format ")), None)
        vertex_count = next(
            int(line.split()[2]) for line in lines if line.startswith("element vertex ")
        )
        property_lines = []
        in_vertex = False
        for line in lines:
            if line.startswith("element vertex "):
                in_vertex = True
            elif line.startswith("element "):
                in_vertex = False
            elif in_vertex and line.startswith("property "):
                fields = line.split()
                if fields[1] == "list":
                    raise ValueError("list properties are unsupported in PLY vertices")
                property_lines.append((fields[1], fields[2]))
        names = [name for _, name in property_lines]
        if not {"x", "y", "z"}.issubset(names):
            raise ValueError("PLY vertex properties do not contain x/y/z")
        if vertex_count <= 0:
            raise ValueError("PLY contains no vertices")

        if fmt == "ascii":
            stream.seek(data_offset)
            points = []
            for _ in range(vertex_count):
                fields = stream.readline().decode("ascii").split()
                points.append([float(fields[names.index(axis)]) for axis in ("x", "y", "z")])
            return np.asarray(points, dtype=float).mean(axis=0) if not points else (
                np.asarray(points, dtype=float).min(axis=0) + np.asarray(points, dtype=float).max(axis=0)
            ) / 2.0

        type_codes = {
            "char": "b", "int8": "b", "uchar": "B", "uint8": "B",
            "short": "h", "int16": "h", "ushort": "H", "uint16": "H",
            "int": "i", "int32": "i", "uint": "I", "uint32": "I",
            "float": "f", "float32": "f", "double": "d", "float64": "d",
        }
        if fmt not in {"binary_little_endian", "binary_big_endian"}:
            raise ValueError(f"unsupported PLY format: {fmt}")
        endian = "<" if fmt == "binary_little_endian" else ">"
        try:
            vertex_format = endian + "".join(type_codes[type_name] for type_name, _ in property_lines)
        except KeyError as exc:
            raise ValueError(f"unsupported PLY property type: {exc.args[0]}") from exc
        stream.seek(data_offset)
        stride = struct.calcsize(vertex_format)
        mins = np.full(3, np.inf)
        maxs = np.full(3, -np.inf)
        indices = [names.index(axis) for axis in ("x", "y", "z")]
        for _ in range(vertex_count):
            values = struct.unpack(vertex_format, stream.read(stride))
            point = np.asarray([values[index] for index in indices], dtype=float)
            mins = np.minimum(mins, point)
            maxs = np.maximum(maxs, point)
        return (mins + maxs) / 2.0


def calculate_anchor(poses, point_cloud_center=None):
    """Return (method, coordinate) using ray, PLY, then camera centroid fallbacks."""
    import numpy as np

    ray_anchor = _solve_ray_intersection(poses)
    if ray_anchor is not None:
        return "robust_ray_intersection", ray_anchor
    if point_cloud_center is not None and np.all(np.isfinite(point_cloud_center)):
        return "point_cloud_bbox_center", np.asarray(point_cloud_center, dtype=float)
    camera_centers = np.asarray([pose[:3, 3] for pose in poses], dtype=float)
    if len(camera_centers) == 0:
        raise ValueError("cannot calculate anchor without camera poses")
    return "camera_position_centroid", camera_centers.mean(axis=0)


def anchor_json(method: str, anchor, coordinate_system: str = "colmap_world") -> str:
    x, y, z = (float(value) for value in anchor)
    return json.dumps(
        {
            "method": method,
            "coordinate_system": coordinate_system,
            "position": {"x": x, "y": y, "z": z},
        },
        ensure_ascii=True,
        indent=2,
    ) + "\n"


def write_anchor(
    job_dir: Path,
    poses_path: Path,
    ply_path: Path,
    coordinate_system: str = "colmap_world",
) -> tuple[Path, str]:
    import numpy as np

    rows = [line.split() for line in poses_path.read_text(encoding="utf-8").splitlines()]
    poses = [np.asarray(row, dtype=float).reshape(4, 4) for row in rows]
    try:
        point_cloud_center = _point_cloud_bbox_center(ply_path)
    except (OSError, ValueError, struct.error):
        point_cloud_center = None
    method, anchor = calculate_anchor(poses, point_cloud_center)
    anchor_path = job_dir / "anchor.json"
    anchor_path.write_text(
        anchor_json(method, anchor, coordinate_system=coordinate_system),
        encoding="utf-8",
    )
    return anchor_path, method


def validate_colmap_output(job_dir: Path) -> None:
    required = [
        job_dir / "images",
        job_dir / "sparse" / "0" / "cameras.bin",
        job_dir / "sparse" / "0" / "images.bin",
        job_dir / "sparse" / "0" / "points3D.bin",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError("COLMAP output is incomplete: " + ", ".join(missing))


def load_colmap_metrics(job_dir: Path) -> dict:
    path = job_dir / "colmap_metrics.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_result(
    path: Path,
    job_id: str,
    status: str,
    stage: str,
    ply_path: Optional[Path],
    exit_code: Optional[int],
    error: Optional[str],
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    poses_path: Optional[Path] = None,
    anchor_path: Optional[Path] = None,
    anchor_method: Optional[str] = None,
    alignment_method: str = "colmap_world",
    gravity_colmap=None,
    alignment_residual_degrees: Optional[float] = None,
) -> None:
    payload = {
        "job_id": job_id,
        "status": status,
        "stage": stage,
        "started_at": started_at,
        "finished_at": finished_at or utc_now(),
        "exit_code": exit_code,
        "error": error,
        "ply_path": str(ply_path) if ply_path else None,
        "size_bytes": ply_path.stat().st_size if ply_path and ply_path.exists() else None,
        "sha256": sha256_file(ply_path) if ply_path and ply_path.exists() else None,
        "poses_path": str(poses_path) if poses_path else None,
        "poses_sha256": sha256_file(poses_path) if poses_path and poses_path.exists() else None,
        "pose_count": len(poses_path.read_text(encoding="utf-8").splitlines()) if poses_path and poses_path.exists() else None,
        "anchor_path": str(anchor_path) if anchor_path else None,
        "anchor_sha256": sha256_file(anchor_path) if anchor_path and anchor_path.exists() else None,
        "anchor_method": anchor_method,
        "alignment_method": alignment_method,
        "gravity_colmap": (
            [float(value) for value in gravity_colmap]
            if gravity_colmap is not None else None
        ),
        "alignment_residual_degrees": alignment_residual_degrees,
    }
    write_json(path, payload)


def append_event(log_path: Path, job_id: str, stage: str, status: str, **fields) -> None:
    payload = {
        "timestamp": utc_now(),
        "job_id": job_id,
        "stage": stage,
        "status": status,
        **fields,
    }
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_command(
    command: list[str],
    stage: str,
    job_id: str,
    job_dir: Path,
    timeout_seconds: int,
    environment: Optional[dict[str, str]] = None,
) -> int:
    stdout_path = job_dir / "stdout.log"
    stderr_path = job_dir / "stderr.log"
    events_path = job_dir / "events.jsonl"
    append_event(events_path, job_id, stage, "started", command=command)
    started = time.monotonic()
    with stdout_path.open("a", encoding="utf-8") as stdout, stderr_path.open("a", encoding="utf-8") as stderr:
        stdout.write(f"\n[{utc_now()}] stage={stage} command={command!r}\n")
        stdout.flush()
        process = subprocess.Popen(
            command,
            cwd=str(job_dir),
            stdout=stdout,
            stderr=stderr,
            text=True,
            env={**os.environ, **(environment or {}), "QT_QPA_PLATFORM": "offscreen"},
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            append_event(
                events_path,
                job_id,
                stage,
                "failed",
                error="timeout",
                duration_seconds=round(time.monotonic() - started, 3),
            )
            raise TimeoutError(f"{stage} timed out after {timeout_seconds}s")

    append_event(
        events_path,
        job_id,
        stage,
        "completed" if return_code == 0 else "failed",
        exit_code=return_code,
        duration_seconds=round(time.monotonic() - started, 3),
    )
    if return_code != 0:
        raise RuntimeError(f"{stage} exited with code {return_code}")
    return return_code


def run_job(args: argparse.Namespace) -> int:
    """Compatibility entry point delegating execution to the decoupled pipeline."""
    from run_pipeline import run_pipeline

    pipeline_args = argparse.Namespace(
        job_dir=args.job_dir,
        fastgs_dir=args.fastgs_dir,
        job_id=args.job_id,
        iterations=args.iterations,
        timeout_seconds=args.timeout_seconds,
        allow_alignment_fallback=getattr(args, "allow_alignment_fallback", False),
        resume_from=getattr(args, "resume_from", None),
        conda_executable=args.conda_executable,
        conda_env=args.conda_env,
        python_executable=args.python_executable,
        colmap_executable=args.colmap_executable,
        max_num_features=args.max_num_features,
        feature_gpu=args.feature_gpu,
        matching_gpu=args.matching_gpu,
        mapper_gpu=args.mapper_use_gpu,
        cuda_lib_dir=args.cuda_lib_dir,
        prune_max_ratio=getattr(args, "prune_max_ratio", 0.01),
        prune_finetune_iterations=getattr(args, "prune_finetune_iterations", 800),
        prune_evaluate_psnr=getattr(args, "prune_evaluate_psnr", True),
    )
    return run_pipeline(pipeline_args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--fastgs-dir", required=True)
    parser.add_argument("--conda-env", default="fastgs")
    parser.add_argument("--conda-executable", default="conda")
    parser.add_argument("--python-executable", default="python")
    parser.add_argument("--iterations", type=int, default=30000)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--job-id")
    parser.add_argument("--colmap-executable", dest="colmap_executable",
                        default=os.getenv("FASTGS_COLMAP_EXECUTABLE", "/home/asus/opt/colmap-cuda-ceres/bin/colmap"))
    parser.add_argument("--colmap_new_api", action="store_true",
                        default=os.getenv("FASTGS_COLMAP_NEW_API", "1") == "1")
    parser.add_argument("--mapper_use_gpu", action="store_true",
                        default=os.getenv("FASTGS_MAPPER_USE_GPU", "1") == "1")
    parser.add_argument("--matching_gpu", action="store_true",
                        default=os.getenv("FASTGS_MATCHING_USE_GPU", "1") == "1")
    parser.add_argument("--feature_gpu", action="store_true",
                        default=os.getenv("FASTGS_FEATURE_USE_GPU", "0") == "1")
    parser.add_argument("--max_num_features", type=int,
                        default=int(os.getenv("FASTGS_MAX_NUM_FEATURES", "8192")))
    parser.add_argument("--cuda-lib-dir",
                        default=os.getenv("FASTGS_CUDA_LIB_DIR", "/usr/local/cuda-12.8/lib64"))
    parser.add_argument("--allow-alignment-fallback", action="store_true")
    parser.add_argument("--resume-from", choices=("colmap", "alignment", "fastgs", "prune", "export"))
    parser.add_argument("--prune-max-ratio", dest="prune_max_ratio", type=float, default=0.01)
    parser.add_argument("--prune-finetune-iterations", dest="prune_finetune_iterations", type=int, default=800)
    parser.add_argument("--prune-evaluate-psnr", dest="prune_evaluate_psnr", action="store_true", default=True)
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    raise SystemExit(run_job(parse_args()))
