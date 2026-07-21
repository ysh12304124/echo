#!/usr/bin/env python3
"""Create a gravity-aligned copy of a COLMAP reconstruction."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

from colmap_model_io import (
    ImageRecord,
    Point3DRecord,
    read_cameras_binary,
    read_images_binary,
    read_points3d_binary,
    validate_colmap_model,
    write_cameras_binary,
    write_images_binary,
    write_points3d_binary,
)
from gravity_alignment import AlignmentResult, estimate_gravity, load_manifest
from pipeline_stage import append_event, utc_now, write_stage_status


def qvec_to_rotmat(qvec: np.ndarray) -> np.ndarray:
    qvec = np.asarray(qvec, dtype=float).reshape(4)
    norm = float(np.linalg.norm(qvec))
    if not np.isfinite(norm) or norm <= 1e-12:
        raise ValueError("COLMAP image quaternion is zero or non-finite")
    w, x, y, z = qvec / norm
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def rotmat_to_qvec(rotation: np.ndarray) -> np.ndarray:
    rotation = np.asarray(rotation, dtype=float).reshape(3, 3)
    trace = float(np.trace(rotation))
    if trace > 0:
        scale = np.sqrt(trace + 1.0) * 2.0
        qvec = np.array([
            0.25 * scale,
            (rotation[2, 1] - rotation[1, 2]) / scale,
            (rotation[0, 2] - rotation[2, 0]) / scale,
            (rotation[1, 0] - rotation[0, 1]) / scale,
        ])
    elif rotation[0, 0] > rotation[1, 1] and rotation[0, 0] > rotation[2, 2]:
        scale = np.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
        qvec = np.array([
            (rotation[2, 1] - rotation[1, 2]) / scale,
            0.25 * scale,
            (rotation[0, 1] + rotation[1, 0]) / scale,
            (rotation[0, 2] + rotation[2, 0]) / scale,
        ])
    elif rotation[1, 1] > rotation[2, 2]:
        scale = np.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
        qvec = np.array([
            (rotation[0, 2] - rotation[2, 0]) / scale,
            (rotation[0, 1] + rotation[1, 0]) / scale,
            0.25 * scale,
            (rotation[1, 2] + rotation[2, 1]) / scale,
        ])
    else:
        scale = np.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
        qvec = np.array([
            (rotation[1, 0] - rotation[0, 1]) / scale,
            (rotation[0, 2] + rotation[2, 0]) / scale,
            (rotation[1, 2] + rotation[2, 1]) / scale,
            0.25 * scale,
        ])
    qvec /= np.linalg.norm(qvec)
    if qvec[0] < 0:
        qvec = -qvec
    return qvec


def _camera_to_world(image: ImageRecord) -> tuple[np.ndarray, np.ndarray]:
    rotation_w2c = qvec_to_rotmat(image.qvec)
    rotation_c2w = rotation_w2c.T
    center = -rotation_c2w @ image.tvec
    return rotation_c2w, center


def _transform_images(images: dict[int, ImageRecord], alignment_rotation: np.ndarray) -> dict[int, ImageRecord]:
    transformed = {}
    for image_id, image in images.items():
        rotation_c2w, center = _camera_to_world(image)
        aligned_c2w = alignment_rotation @ rotation_c2w
        aligned_center = alignment_rotation @ center
        aligned_w2c = aligned_c2w.T
        transformed[image_id] = ImageRecord(
            image_id=image.image_id,
            qvec=rotmat_to_qvec(aligned_w2c),
            tvec=-aligned_w2c @ aligned_center,
            camera_id=image.camera_id,
            name=image.name,
            xys=image.xys.copy(),
            point3d_ids=image.point3d_ids.copy(),
        )
    return transformed


def _transform_points(points: dict[int, Point3DRecord], alignment_rotation: np.ndarray) -> dict[int, Point3DRecord]:
    return {
        point_id: Point3DRecord(
            point3d_id=point.point3d_id,
            xyz=alignment_rotation @ point.xyz,
            rgb=point.rgb.copy(),
            error=point.error,
            image_ids=point.image_ids.copy(),
            point2d_idxs=point.point2d_idxs.copy(),
        )
        for point_id, point in points.items()
    }


def _link_or_copy(source: str, destination: str) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _copy_raw_model(raw_dir: Path, target_dir: Path) -> None:
    shutil.copytree(raw_dir, target_dir, copy_function=_link_or_copy, dirs_exist_ok=True)


def _poses_by_image(images: dict[int, ImageRecord]) -> dict[str, np.ndarray]:
    return {
        image.name: np.block([
            [_camera_to_world(image)[0], _camera_to_world(image)[1].reshape(3, 1)],
            [np.zeros((1, 3)), np.ones((1, 1))],
        ])
        for image in images.values()
    }


def _alignment_metadata(alignment: AlignmentResult, fallback: bool = False, fallback_reason: Optional[str] = None) -> dict:
    return {
        "version": 1,
        "method": alignment.method,
        "coordinate_system": alignment.coordinate_system,
        "gravity_colmap": alignment.gravity_colmap.tolist() if alignment.gravity_colmap is not None else None,
        "target_gravity": [0.0, 1.0, 0.0] if alignment.method == "gravity_aligned_world" else None,
        "rotation_matrix": alignment.rotation.tolist(),
        "residual_degrees": alignment.residual_degrees,
        "valid_sample_count": alignment.valid_sample_count,
        "fallback": fallback,
        "fallback_reason": fallback_reason,
    }


def align_colmap_model(input_dir: Path, manifest_path: Path, output_dir: Path, allow_fallback: bool = False) -> dict:
    validate_colmap_model(input_dir / "sparse" / "0")
    images = read_images_binary(input_dir / "sparse" / "0" / "images.bin")
    poses = _poses_by_image(images)
    try:
        manifest = load_manifest(manifest_path)
        alignment = estimate_gravity(manifest, poses, [image.name for image in images.values()])
        if alignment.method != "gravity_aligned_world":
            raise ValueError("no valid matched IMU acceleration")
    except Exception as exc:
        if not allow_fallback:
            raise
        if output_dir.exists():
            shutil.rmtree(output_dir)
        _copy_raw_model(input_dir, output_dir)
        fallback = AlignmentResult("colmap_world", "colmap_world", np.eye(3), None, None, 0)
        metadata = _alignment_metadata(fallback, fallback=True, fallback_reason=str(exc))
        (output_dir / "alignment_meta.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        return metadata

    temporary_dir = Path(tempfile.mkdtemp(prefix=".%s." % output_dir.name, dir=str(output_dir.parent)))
    try:
        _copy_raw_model(input_dir, temporary_dir)
        raw_model = input_dir / "sparse" / "0"
        target_model = temporary_dir / "sparse" / "0"
        transformed_images = _transform_images(images, alignment.rotation)
        transformed_points = _transform_points(
            read_points3d_binary(raw_model / "points3D.bin"), alignment.rotation
        )
        write_images_binary(target_model / "images.bin", transformed_images)
        write_points3d_binary(target_model / "points3D.bin", transformed_points)
        # FastGS prefers this cache over points3D.bin; force regeneration from
        # the transformed binary model instead of leaving stale raw coordinates.
        for stale_ply in (target_model / "points3D.ply", target_model / "points3d.ply"):
            stale_ply.unlink(missing_ok=True)
        metadata = _alignment_metadata(alignment)
        (temporary_dir / "alignment_meta.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        validate_colmap_model(target_model)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        os.replace(temporary_dir, output_dir)
        return metadata
    finally:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)


def run_alignment_stage(args: argparse.Namespace) -> int:
    job_dir = Path(args.job_dir).resolve()
    input_dir = job_dir / "colmap_raw"
    output_dir = job_dir / "colmap_gravity_aligned"
    status_path = job_dir / "stages" / "alignment" / "status.json"
    events_path = job_dir / "events.jsonl"
    job_id = args.job_id or job_dir.name
    started_at = utc_now()
    write_stage_status(status_path, {"version": 1, "job_id": job_id, "stage": "alignment", "status": "running", "started_at": started_at, "finished_at": None, "error_code": None, "message": "Gravity alignment is running.", "warnings": []})
    try:
        metadata = align_colmap_model(input_dir, job_dir / "imu_manifest.json", output_dir, args.allow_alignment_fallback)
        status = "completed_with_warnings" if metadata["fallback"] else "completed"
        payload = {"version": 1, "job_id": job_id, "stage": "alignment", "status": status, "started_at": started_at, "finished_at": utc_now(), "error_code": None, "message": "COLMAP gravity alignment completed.", "input": {"colmap_dir": str(input_dir)}, "output": {"colmap_dir": str(output_dir)}, "metrics": metadata, "warnings": [metadata["fallback_reason"]] if metadata["fallback"] else []}
        write_stage_status(status_path, payload)
        append_event(events_path, {"timestamp": payload["finished_at"], "job_id": job_id, "stage": "alignment", "status": status, "metrics": metadata})
        return 0
    except Exception as exc:
        payload = {"version": 1, "job_id": job_id, "stage": "alignment", "status": "failed", "started_at": started_at, "finished_at": utc_now(), "error_code": "GRAVITY_ALIGNMENT_ERROR", "message": str(exc), "warnings": []}
        write_stage_status(status_path, payload)
        append_event(events_path, {"timestamp": payload["finished_at"], "job_id": job_id, "stage": "alignment", "status": "failed", "error_code": payload["error_code"], "message": str(exc)})
        print("alignment stage failed: %s" % exc, file=sys.stderr)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--job-id")
    parser.add_argument("--allow-alignment-fallback", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_alignment_stage(parse_args()))
