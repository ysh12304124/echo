#!/usr/bin/env python3
"""Export final poses, Gaussian PLY, anchor, and result JSON."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from plyfile import PlyData

from anchor_calculator import calculate_anchor, point_cloud_bbox_center
from colmap_model_io import ImageRecord, read_images_binary
from pipeline_stage import append_event, utc_now, write_stage_status
from run_prune import find_pruned_outputs


@dataclass(frozen=True)
class PoseRecord:
    image: str
    timestamp_ms: Optional[int]
    matrix: np.ndarray


def _camera_to_world(image: ImageRecord) -> np.ndarray:
    qvec = np.asarray(image.qvec, dtype=float)
    norm = np.linalg.norm(qvec)
    if not np.isfinite(norm) or norm <= 1e-12:
        raise ValueError("invalid COLMAP quaternion for %s" % image.name)
    w, x, y, z = qvec / norm
    rotation_w2c = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])
    rotation_c2w = rotation_w2c.T
    center = -rotation_c2w @ np.asarray(image.tvec, dtype=float)
    matrix = np.eye(4, dtype=float)
    matrix[:3, :3] = rotation_c2w
    matrix[:3, 3] = center
    return matrix


def _read_timestamps(manifest_path: Path) -> dict[str, int]:
    if not manifest_path.is_file():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = {}
    for frame in payload.get("frames", []):
        if isinstance(frame, dict) and isinstance(frame.get("image"), str) and isinstance(frame.get("timestamp_ms"), (int, float)):
            result[frame["image"]] = int(frame["timestamp_ms"])
    return result


def _coordinate_system(aligned_dir: Path) -> str:
    metadata_path = aligned_dir / "alignment_meta.json"
    if not metadata_path.is_file():
        return "colmap_world"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    coordinate_system = payload.get("coordinate_system")
    if coordinate_system not in {"colmap_world", "gravity_aligned_world"}:
        raise ValueError("unsupported coordinate system in alignment_meta.json")
    return coordinate_system


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(".%s.tmp" % destination.name)
    shutil.copy2(source, temporary)
    temporary.replace(destination)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".%s.tmp" % path.name)
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _validate_gaussian_ply(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("FastGS PLY output is missing or empty: %s" % path)
    try:
        vertex = PlyData.read(str(path))["vertex"]
        names = set(vertex.data.dtype.names or ())
        if len(vertex.data) == 0 or not {"x", "y", "z"}.issubset(names):
            raise ValueError("FastGS PLY does not contain a usable vertex element")
    except (OSError, KeyError, ValueError) as exc:
        raise ValueError("FastGS PLY is malformed: %s" % path) from exc


def export_outputs(aligned_dir: Path, ply_path: Path, input_dir: Path, output_dir: Path, manifest_path: Optional[Path] = None) -> Path:
    _validate_gaussian_ply(ply_path)
    images = read_images_binary(aligned_dir / "sparse" / "0" / "images.bin")
    input_images = sorted(path.name for path in input_dir.iterdir() if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"})
    registered_by_name = {image.name: image for image in images.values()}
    missing = [name for name in input_images if name not in registered_by_name]
    timestamps = _read_timestamps(manifest_path) if manifest_path else {}
    coordinate_system = _coordinate_system(aligned_dir)
    pose_records = [PoseRecord(name, timestamps.get(name), _camera_to_world(registered_by_name[name])) for name in input_images if name in registered_by_name]
    if not pose_records:
        raise ValueError("NO_REGISTERED_POSES")
    poses = [record.matrix for record in pose_records]
    try:
        center = point_cloud_bbox_center(ply_path)
    except ValueError:
        center = None
    anchor_method, anchor = calculate_anchor(poses, center)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_ply = output_dir / "point_cloud.ply"
    _atomic_copy(ply_path, output_ply)
    poses_payload = {
        "version": 1,
        "coordinate_system": coordinate_system,
        "pose_type": "camera_to_world",
        "input_image_count": len(input_images),
        "registered_image_count": len(pose_records),
        "registration_ratio": len(pose_records) / len(input_images) if input_images else 0.0,
        "poses": [{"image": record.image, "timestamp_ms": record.timestamp_ms, "matrix": record.matrix.tolist()} for record in pose_records],
        "unregistered_images": missing,
    }
    _write_json(output_dir / "poses.json", poses_payload)
    poses_text = "\n".join(" ".join("%.15f" % value for value in record.matrix.reshape(-1)) for record in pose_records) + "\n"
    (output_dir / "poses.txt").write_text(poses_text, encoding="utf-8")
    _write_json(output_dir / "anchor.json", {"version": 1, "method": anchor_method, "coordinate_system": coordinate_system, "position": {"x": float(anchor[0]), "y": float(anchor[1]), "z": float(anchor[2])}})
    _write_json(output_dir / "result.json", {"version": 1, "status": "completed", "coordinate_system": coordinate_system, "registered_image_count": len(pose_records), "input_image_count": len(input_images), "registration_ratio": poses_payload["registration_ratio"], "outputs": {"point_cloud": str(output_ply), "poses_json": str(output_dir / "poses.json"), "poses_txt": str(output_dir / "poses.txt"), "anchor": str(output_dir / "anchor.json")}, "anchor_method": anchor_method})
    return output_dir


def run_export_stage(args: argparse.Namespace) -> int:
    job_dir = Path(args.job_dir).resolve()
    stage_dir = job_dir / "stages" / "export"
    status_path = stage_dir / "status.json"
    events_path = job_dir / "events.jsonl"
    job_id = args.job_id or job_dir.name
    started_at = utc_now()
    write_stage_status(status_path, {"version": 1, "job_id": job_id, "stage": "export", "status": "running", "started_at": started_at, "finished_at": None, "error_code": None, "message": "Export is running.", "warnings": []})
    try:
        pruned = find_pruned_outputs(job_dir / "fastgs_model", args.iterations)
        output_dir = export_outputs(job_dir / "colmap_gravity_aligned", pruned["ply"], job_dir / "input", job_dir / "outputs", job_dir / "imu_manifest.json")
        payload = {"version": 1, "job_id": job_id, "stage": "export", "status": "completed", "started_at": started_at, "finished_at": utc_now(), "error_code": None, "message": "Final pruned outputs exported.", "output": {"output_dir": str(output_dir), "source_ply": str(pruned["ply"]), "prune_stats": str(pruned["stats"])}, "warnings": []}
        write_stage_status(status_path, payload)
        append_event(events_path, {"timestamp": payload["finished_at"], "job_id": job_id, "stage": "export", "status": "completed", "output_dir": str(output_dir)})
        return 0
    except Exception as exc:
        payload = {"version": 1, "job_id": job_id, "stage": "export", "status": "failed", "started_at": started_at, "finished_at": utc_now(), "error_code": "EXPORT_STAGE_ERROR", "message": str(exc), "warnings": []}
        write_stage_status(status_path, payload)
        append_event(events_path, {"timestamp": payload["finished_at"], "job_id": job_id, "stage": "export", "status": "failed", "error_code": payload["error_code"], "message": str(exc)})
        print("export stage failed: %s" % exc, file=sys.stderr)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--job-id")
    parser.add_argument("--iterations", type=int, default=30000)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_export_stage(parse_args()))
