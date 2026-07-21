"""Pure anchor calculation helpers for final FastGS exports."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from plyfile import PlyData


def _solve_ray_intersection(poses: list[np.ndarray]) -> Optional[np.ndarray]:
    if len(poses) < 3:
        return None
    origins = np.asarray([pose[:3, 3] for pose in poses], dtype=float)
    directions = np.asarray([pose[:3, 2] for pose in poses], dtype=float)
    norms = np.linalg.norm(directions, axis=1)
    if np.any(~np.isfinite(norms)) or np.any(norms <= 1e-9):
        return None
    directions = directions / norms[:, None]
    projectors = np.eye(3)[None, :, :] - directions[:, :, None] * directions[:, None, :]
    weights = np.ones(len(poses), dtype=float)
    anchor = None
    for _ in range(8):
        weighted = projectors * weights[:, None, None]
        matrix = weighted.sum(axis=0)
        vector = np.einsum("nij,nj->i", weighted, origins)
        if np.linalg.matrix_rank(matrix, tol=1e-8) < 3:
            return None
        condition = np.linalg.cond(matrix)
        if not np.isfinite(condition) or condition > 1e8:
            return None
        try:
            anchor = np.linalg.solve(matrix, vector)
        except np.linalg.LinAlgError:
            return None
        residuals = np.linalg.norm(
            np.einsum("nij,nj->ni", projectors, anchor - origins), axis=1
        )
        scale = max(float(np.median(residuals)), 1e-6)
        weights = np.minimum(1.0, (1.5 * scale) / np.maximum(residuals, 1e-9))
    if anchor is None or not np.all(np.isfinite(anchor)):
        return None
    return anchor


def point_cloud_bbox_center(ply_path: Path) -> np.ndarray:
    try:
        vertex = PlyData.read(str(ply_path))["vertex"]
        names = set(vertex.data.dtype.names or ())
        if not {"x", "y", "z"}.issubset(names):
            raise ValueError("PLY vertex properties do not contain x/y/z")
        if len(vertex.data) == 0:
            raise ValueError("PLY contains no vertices")
        points = np.column_stack([vertex[name].astype(float) for name in ("x", "y", "z")])
        center = (points.min(axis=0) + points.max(axis=0)) / 2.0
        if not np.all(np.isfinite(center)):
            raise ValueError("PLY bounding-box center is non-finite")
        return center
    except (OSError, KeyError, ValueError) as exc:
        raise ValueError("cannot calculate PLY bounding-box center: %s" % ply_path) from exc


def calculate_anchor(
    poses: list[np.ndarray],
    point_cloud_center: Optional[np.ndarray],
) -> tuple[str, np.ndarray]:
    if not poses:
        raise ValueError("NO_REGISTERED_POSES")
    ray_anchor = _solve_ray_intersection(poses)
    if ray_anchor is not None:
        return "robust_ray_intersection", ray_anchor
    if point_cloud_center is not None:
        point_cloud_center = np.asarray(point_cloud_center, dtype=float).reshape(3)
        if np.all(np.isfinite(point_cloud_center)):
            return "point_cloud_bbox_center", point_cloud_center
    camera_centers = np.asarray([pose[:3, 3] for pose in poses], dtype=float)
    if camera_centers.ndim != 2 or camera_centers.shape[1] != 3:
        raise ValueError("INVALID_CAMERA_POSES")
    anchor = camera_centers.mean(axis=0)
    if not np.all(np.isfinite(anchor)):
        raise ValueError("NONFINITE_CAMERA_POSES")
    return "camera_position_centroid", anchor
