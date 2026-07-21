"""Manifest parsing and gravity-frame math for FastGS post-processing."""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from plyfile import PlyData


log = logging.getLogger(__name__)


class ManifestError(ValueError):
    """Raised when the optional IMU manifest cannot be interpreted."""


@dataclass(frozen=True)
class ManifestFrame:
    image: str
    timestamp_ms: int
    acceleration: Tuple[float, float, float]


@dataclass(frozen=True)
class Manifest:
    acceleration_type: str
    frames: Dict[str, ManifestFrame]


@dataclass(frozen=True)
class AlignmentResult:
    method: str
    coordinate_system: str
    rotation: np.ndarray
    gravity_colmap: Optional[np.ndarray]
    residual_degrees: Optional[float]
    valid_sample_count: int


def _fallback_result() -> AlignmentResult:
    return AlignmentResult(
        method="colmap_world",
        coordinate_system="colmap_world",
        rotation=np.eye(3, dtype=float),
        gravity_colmap=None,
        residual_degrees=None,
        valid_sample_count=0,
    )


def _finite_vector(value, length: int) -> Optional[np.ndarray]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return None
    try:
        vector = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    if vector.shape != (length,) or not np.all(np.isfinite(vector)):
        return None
    return vector


def load_manifest(path: Path) -> Manifest:
    """Load the versioned image-to-camera-acceleration manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError("IMU manifest does not exist: %s" % path) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("cannot read IMU manifest: %s" % path) from exc

    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ManifestError("IMU manifest version must be 1")
    if payload.get("acceleration_frame") != "camera":
        raise ManifestError("IMU acceleration_frame must be camera")
    acceleration_type = payload.get("acceleration_type")
    if acceleration_type not in {"gravity", "specific_force"}:
        raise ManifestError("unsupported IMU acceleration_type")
    entries = payload.get("frames")
    if not isinstance(entries, list):
        raise ManifestError("IMU manifest frames must be a list")

    frames: Dict[str, ManifestFrame] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        image = entry.get("image")
        timestamp_ms = entry.get("timestamp_ms")
        acceleration = _finite_vector(entry.get("acceleration"), 3)
        if (
            not isinstance(image, str)
            or not image
            or image in frames
            or isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, (int, float))
            or not float(timestamp_ms).is_integer()
            or acceleration is None
        ):
            continue
        frames[image] = ManifestFrame(
            image=image,
            timestamp_ms=int(timestamp_ms),
            acceleration=tuple(float(value) for value in acceleration),
        )
    return Manifest(acceleration_type=acceleration_type, frames=frames)


def _normalize(vector: np.ndarray) -> Optional[np.ndarray]:
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 1e-9:
        return None
    return vector / norm


def rotation_to_target(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Return the minimum-angle proper rotation mapping source to target."""
    source_unit = _normalize(np.asarray(source, dtype=float))
    target_unit = _normalize(np.asarray(target, dtype=float))
    if source_unit is None or target_unit is None:
        raise ValueError("rotation vectors must be finite and non-zero")

    dot = float(np.clip(np.dot(source_unit, target_unit), -1.0, 1.0))
    if dot >= 1.0 - 1e-10:
        return np.eye(3, dtype=float)
    if dot <= -1.0 + 1e-10:
        return np.diag([1.0, -1.0, -1.0]).astype(float)

    cross = np.cross(source_unit, target_unit)
    sine = float(np.linalg.norm(cross))
    skew = np.array([
        [0.0, -cross[2], cross[1]],
        [cross[2], 0.0, -cross[0]],
        [-cross[1], cross[0], 0.0],
    ])
    return np.eye(3) + skew + skew @ skew * ((1.0 - dot) / (sine * sine))


def estimate_gravity(
    manifest: Manifest,
    poses_by_image: Dict[str, np.ndarray],
    image_names: List[str],
) -> AlignmentResult:
    """Estimate downward gravity in COLMAP coordinates and its alignment rotation."""
    if len(manifest.frames) == 0:
        return _fallback_result()

    world_vectors = []
    for image_name in image_names:
        frame = manifest.frames.get(image_name)
        pose = poses_by_image.get(image_name)
        if frame is None or pose is None:
            continue
        acceleration = np.asarray(frame.acceleration, dtype=float)
        magnitude = float(np.linalg.norm(acceleration))
        if not np.isfinite(magnitude) or magnitude < 0.5 or magnitude > 20.0:
            continue
        if manifest.acceleration_type == "specific_force":
            acceleration = -acceleration
        camera_direction = _normalize(acceleration)
        if camera_direction is None:
            continue
        pose = np.asarray(pose, dtype=float)
        if pose.shape != (4, 4) or not np.all(np.isfinite(pose)):
            continue
        world_direction = _normalize(pose[:3, :3] @ camera_direction)
        if world_direction is not None:
            world_vectors.append(world_direction)

    valid_count = len(world_vectors)
    if valid_count == 0:
        return _fallback_result()

    vectors = np.asarray(world_vectors, dtype=float)
    median_direction = _normalize(np.median(vectors, axis=0))
    if median_direction is None:
        return _fallback_result()
    angles = np.degrees(np.arccos(np.clip(vectors @ median_direction, -1.0, 1.0)))
    inlier_mask = angles <= 20.0
    inliers = vectors[inlier_mask]
    if len(inliers) == 0:
        return _fallback_result()
    gravity = _normalize(inliers.mean(axis=0))
    if gravity is None:
        return _fallback_result()

    rotation = rotation_to_target(gravity, np.array([0.0, 1.0, 0.0]))
    residual = float(np.degrees(np.arccos(np.clip(np.dot(rotation @ gravity, [0.0, 1.0, 0.0]), -1.0, 1.0))))
    return AlignmentResult(
        method="gravity_aligned_world",
        coordinate_system="gravity_aligned_world",
        rotation=rotation,
        gravity_colmap=gravity,
        residual_degrees=residual,
        valid_sample_count=len(inliers),
    )


def transform_poses(
    poses_by_image: Dict[str, np.ndarray], rotation: np.ndarray
) -> Dict[str, np.ndarray]:
    """Rotate C2W poses into the aligned world frame."""
    aligned: Dict[str, np.ndarray] = {}
    rotation = np.asarray(rotation, dtype=float)
    for image, pose in poses_by_image.items():
        matrix = np.asarray(pose, dtype=float).copy()
        if matrix.shape != (4, 4):
            raise ValueError("pose for %s is not a 4x4 matrix" % image)
        matrix[:3, :3] = rotation @ matrix[:3, :3]
        matrix[:3, 3] = rotation @ matrix[:3, 3]
        aligned[image] = matrix
    return aligned


def _parse_pose_text(text: str) -> List[np.ndarray]:
    poses = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 16:
            raise ValueError("pose line %d must contain 16 values" % line_number)
        try:
            values = np.asarray([float(value) for value in fields], dtype=float)
        except ValueError as exc:
            raise ValueError("pose line %d contains a non-numeric value" % line_number) from exc
        if not np.all(np.isfinite(values)):
            raise ValueError("pose line %d contains a non-finite value" % line_number)
        poses.append(values.reshape(4, 4))
    return poses


def transform_pose_text(text: str, rotation: np.ndarray) -> str:
    """Transform and serialize row-major C2W pose rows."""
    poses = transform_poses(
        {str(index): pose for index, pose in enumerate(_parse_pose_text(text))},
        rotation,
    )
    return "\n".join(
        " ".join("%.15f" % value for value in poses[str(index)].reshape(-1))
        for index in range(len(poses))
    ) + ("\n" if poses else "")


def _quaternion_to_matrix(quaternion: np.ndarray) -> np.ndarray:
    quaternion = np.asarray(quaternion, dtype=float)
    norm = float(np.linalg.norm(quaternion))
    if not np.isfinite(norm) or norm <= 1e-9:
        raise ValueError("Gaussian quaternion is zero or non-finite")
    w, x, y, z = quaternion / norm
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def _matrix_to_quaternion(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=float)
    trace = float(np.trace(matrix))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        quaternion = np.array([
            0.25 * scale,
            (matrix[2, 1] - matrix[1, 2]) / scale,
            (matrix[0, 2] - matrix[2, 0]) / scale,
            (matrix[1, 0] - matrix[0, 1]) / scale,
        ])
    elif matrix[0, 0] > matrix[1, 1] and matrix[0, 0] > matrix[2, 2]:
        scale = math.sqrt(1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2]) * 2.0
        quaternion = np.array([
            (matrix[2, 1] - matrix[1, 2]) / scale,
            0.25 * scale,
            (matrix[0, 1] + matrix[1, 0]) / scale,
            (matrix[0, 2] + matrix[2, 0]) / scale,
        ])
    elif matrix[1, 1] > matrix[2, 2]:
        scale = math.sqrt(1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2]) * 2.0
        quaternion = np.array([
            (matrix[0, 2] - matrix[2, 0]) / scale,
            (matrix[0, 1] + matrix[1, 0]) / scale,
            0.25 * scale,
            (matrix[1, 2] + matrix[2, 1]) / scale,
        ])
    else:
        scale = math.sqrt(1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1]) * 2.0
        quaternion = np.array([
            (matrix[1, 0] - matrix[0, 1]) / scale,
            (matrix[0, 2] + matrix[2, 0]) / scale,
            (matrix[1, 2] + matrix[2, 1]) / scale,
            0.25 * scale,
        ])
    return quaternion / np.linalg.norm(quaternion)


def _atomic_write_ply(path: Path, ply_data: PlyData) -> None:
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".%s." % path.name,
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        ply_data.write(str(temporary_path))
        os.replace(str(temporary_path), str(path))
    finally:
        temporary_path.unlink(missing_ok=True)


def transform_gaussian_ply(path: Path, rotation: np.ndarray) -> None:
    """Rotate Gaussian positions and FastGS wxyz rotations in-place."""
    ply_data = PlyData.read(str(path))
    if not ply_data.elements or ply_data["vertex"] is None:
        raise ValueError("PLY does not contain a vertex element")
    vertex = ply_data["vertex"]
    names = set(vertex.data.dtype.names or ())
    required = {"x", "y", "z", "rot_0", "rot_1", "rot_2", "rot_3"}
    if not required.issubset(names):
        raise ValueError("Gaussian PLY is missing required position or rotation fields")

    positions = np.column_stack([vertex[name].astype(float) for name in ("x", "y", "z")])
    transformed_positions = (np.asarray(rotation, dtype=float) @ positions.T).T
    for index, name in enumerate(("x", "y", "z")):
        vertex.data[name] = transformed_positions[:, index]

    transformed_quaternions = []
    for index in range(len(vertex.data)):
        quaternion = np.array([
            vertex.data["rot_0"][index], vertex.data["rot_1"][index],
            vertex.data["rot_2"][index], vertex.data["rot_3"][index],
        ])
        transformed_quaternions.append(
            _matrix_to_quaternion(np.asarray(rotation, dtype=float) @ _quaternion_to_matrix(quaternion))
        )
    transformed_quaternions = np.asarray(transformed_quaternions, dtype=float)
    for index, name in enumerate(("rot_0", "rot_1", "rot_2", "rot_3")):
        vertex.data[name] = transformed_quaternions[:, index]
    _atomic_write_ply(path, ply_data)


def _poses_by_image(text: str, image_names: List[str]) -> Dict[str, np.ndarray]:
    poses = _parse_pose_text(text)
    if len(poses) != len(image_names):
        raise ValueError("pose count does not match input image count")
    return dict(zip(image_names, poses))


def _atomic_write_text(path: Path, text: str) -> None:
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".%s." % path.name,
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(str(temporary_path), str(path))
    finally:
        temporary_path.unlink(missing_ok=True)


def apply_gravity_alignment(
    manifest_path: Path,
    poses_path: Path,
    ply_path: Path,
    image_names: List[str],
) -> AlignmentResult:
    """Apply alignment atomically, returning COLMAP fallback on bad optional input."""
    try:
        manifest = load_manifest(manifest_path)
        pose_text = poses_path.read_text(encoding="utf-8")
        poses = _poses_by_image(pose_text, image_names)
        alignment = estimate_gravity(manifest, poses, image_names)
        if alignment.method != "gravity_aligned_world":
            return alignment

        transformed_pose_text = transform_pose_text(pose_text, alignment.rotation)
        ply_data = PlyData.read(str(ply_path))
        if not ply_data.elements or "vertex" not in [element.name for element in ply_data.elements]:
            raise ValueError("PLY does not contain a vertex element")

        # Build both transformed artifacts in temporary paths before publishing either one.
        pose_fd, pose_name = tempfile.mkstemp(
            prefix=".%s." % poses_path.name,
            suffix=".tmp",
            dir=str(poses_path.parent),
            text=True,
        )
        ply_fd, ply_name = tempfile.mkstemp(
            prefix=".%s." % ply_path.name,
            suffix=".tmp",
            dir=str(ply_path.parent),
        )
        pose_temp = Path(pose_name)
        ply_temp = Path(ply_name)
        os.close(pose_fd)
        os.close(ply_fd)
        pose_backup_fd, pose_backup_name = tempfile.mkstemp(
            prefix=".%s.backup." % poses_path.name,
            dir=str(poses_path.parent),
        )
        ply_backup_fd, ply_backup_name = tempfile.mkstemp(
            prefix=".%s.backup." % ply_path.name,
            dir=str(ply_path.parent),
        )
        os.close(pose_backup_fd)
        os.close(ply_backup_fd)
        pose_backup = Path(pose_backup_name)
        ply_backup = Path(ply_backup_name)
        try:
            shutil.copy2(str(poses_path), str(pose_backup))
            shutil.copy2(str(ply_path), str(ply_backup))
            pose_temp.write_text(transformed_pose_text, encoding="utf-8")
            shutil.copy2(str(ply_path), str(ply_temp))
            transform_gaussian_ply(ply_temp, alignment.rotation)
            os.replace(str(pose_temp), str(poses_path))
            try:
                os.replace(str(ply_temp), str(ply_path))
            except Exception:
                shutil.copy2(str(pose_backup), str(poses_path))
                raise
        finally:
            pose_temp.unlink(missing_ok=True)
            ply_temp.unlink(missing_ok=True)
            pose_backup.unlink(missing_ok=True)
            ply_backup.unlink(missing_ok=True)
        return alignment
    except (ManifestError, OSError, ValueError, TypeError, KeyError) as exc:
        log.warning("gravity alignment fallback to colmap_world: %s", exc)
        return _fallback_result()
