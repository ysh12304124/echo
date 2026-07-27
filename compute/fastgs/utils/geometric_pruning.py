"""COLMAP-backed multi-view geometric support for conservative Gaussian pruning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable

import numpy as np
import torch
from scipy.spatial import cKDTree


def project_points(xyz, rotation, translation, fx, fy, cx, cy, width, height):
    camera_xyz = xyz @ rotation.transpose(0, 1) + translation
    depth = camera_xyz[:, 2]
    safe_depth = depth.clamp_min(1e-8)
    uv = torch.stack((fx * camera_xyz[:, 0] / safe_depth + cx,
                      fy * camera_xyz[:, 1] / safe_depth + cy), dim=1)
    valid = (
        (depth > 0)
        & (uv[:, 0] >= 0)
        & (uv[:, 0] < width)
        & (uv[:, 1] >= 0)
        & (uv[:, 1] < height)
    )
    return uv, depth, valid


@dataclass
class CameraObservationIndex:
    tree: cKDTree
    pixels: np.ndarray
    depths: np.ndarray


def build_observation_indices(cameras, images, points3d):
    indices: Dict[int, CameraObservationIndex] = {}
    for image_id, image in images.items():
        camera = cameras[image.camera_id]
        valid_ids = [int(point_id) for point_id in image.point3d_ids if int(point_id) in points3d]
        if not valid_ids:
            continue

        pixels = []
        depths = []
        point_id_array = image.point3d_ids.astype(np.int64)
        for point_id, pixel in zip(point_id_array, image.xys):
            point = points3d.get(int(point_id))
            if point is None:
                continue
            xyz = np.asarray(point.xyz, dtype=float)
            rotation = qvec2rotmat(image.qvec)
            depth = float((rotation @ xyz + image.tvec)[2])
            if depth > 0:
                pixels.append(pixel)
                depths.append(depth)
        if pixels:
            pixel_array = np.asarray(pixels, dtype=float)
            indices[image_id] = CameraObservationIndex(
                tree=cKDTree(pixel_array),
                pixels=pixel_array,
                depths=np.asarray(depths, dtype=float),
            )
    return indices


def qvec2rotmat(qvec):
    w, x, y, z = qvec
    return np.asarray([
        [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * z * w, 2 * x * z + 2 * y * w],
        [2 * x * y + 2 * z * w, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * x * w],
        [2 * x * z - 2 * y * w, 2 * y * z + 2 * x * w, 1 - 2 * x * x - 2 * y * y],
    ], dtype=float)


def camera_intrinsics(camera):
    if camera.model_id == 0:
        f, cx, cy = camera.params
        return float(f), float(f), float(cx), float(cy)
    if camera.model_id == 1:
        fx, fy, cx, cy = camera.params
        return float(fx), float(fy), float(cx), float(cy)
    raise ValueError("geometric pruning supports PINHOLE/SIMPLE_PINHOLE only")


def collect_geometric_support(
    xyz,
    cameras,
    images,
    observation_indices,
    pixel_radius=3.0,
    depth_absolute_tolerance=0.05,
    depth_relative_tolerance=0.05,
):
    points = xyz.detach().float().cpu()
    support = np.zeros(len(points), dtype=np.int32)
    conflicts = np.zeros(len(points), dtype=np.int32)

    for image_id, image in images.items():
        index = observation_indices.get(image_id)
        if index is None:
            continue
        camera = cameras[image.camera_id]
        fx, fy, cx, cy = camera_intrinsics(camera)
        rotation = torch.from_numpy(qvec2rotmat(image.qvec)).float()
        translation = torch.from_numpy(np.asarray(image.tvec, dtype=float)).float()
        uv, depth, valid = project_points(
            points, rotation, translation, fx, fy, cx, cy, camera.width, camera.height,
        )
        valid_indices = valid.nonzero(as_tuple=False).flatten().numpy()
        if not len(valid_indices):
            continue
        distances, nearest = index.tree.query(
            uv[valid_indices].numpy(), distance_upper_bound=pixel_radius,
        )
        matched = np.isfinite(distances) & (nearest < len(index.depths))
        if not matched.any():
            continue
        point_indices = valid_indices[matched]
        observed_depth = index.depths[nearest[matched]]
        predicted_depth = depth[point_indices].numpy()
        tolerance = depth_absolute_tolerance + depth_relative_tolerance * observed_depth
        consistent = np.abs(predicted_depth - observed_depth) <= tolerance
        support[point_indices[consistent]] += 1
        conflicts[point_indices[~consistent]] += 1

    device = xyz.device
    return (
        torch.from_numpy(support).to(device=device),
        torch.from_numpy(conflicts).to(device=device),
    )


def select_evaluation_cameras(train_cameras, test_cameras):
    if test_cameras:
        return test_cameras, "test"
    return train_cameras, "train"


def knn_isolation_mask(xyz, knn_k=8, mad_factor=4.0, scaling=None):
    if knn_k < 1 or xyz.shape[0] <= knn_k:
        raise ValueError("knn_k must be positive and smaller than the Gaussian count")
    points = xyz.detach().float().cpu().numpy()
    distances, _ = cKDTree(points).query(points, k=knn_k + 1, workers=-1)
    kth = np.asarray(distances[:, knn_k], dtype=np.float32)
    isolation_distance = kth
    if scaling is not None:
        scale = scaling.detach().float().cpu().numpy()
        scale_radius = np.cbrt(np.maximum(np.prod(scale, axis=1), 1e-12))
        isolation_distance = kth / scale_radius
    median = float(np.median(isolation_distance))
    mad = float(np.median(np.abs(isolation_distance - median)))
    threshold = median + mad_factor * mad
    return (
        torch.from_numpy(isolation_distance > threshold).to(device=xyz.device),
        torch.from_numpy(isolation_distance).to(device=xyz.device),
        threshold,
    )


def compute_render_importance(opacity, visibility_count, max_screen_radius):
    return opacity * visibility_count.float() * max_screen_radius.square().clamp_min(1.0)


def screen_overlap_loser_mask(
    uv,
    depth,
    radii,
    importance,
    depth_absolute_tolerance,
    depth_relative_tolerance,
    dominance_ratio,
    max_neighbors,
    candidate_mask=None,
):
    if dominance_ratio <= 1.0:
        raise ValueError("dominance_ratio must be greater than 1")
    if max_neighbors < 1:
        raise ValueError("max_neighbors must be positive")

    device = uv.device
    uv_cpu = uv.detach().float().cpu().numpy()
    depth_cpu = depth.detach().float().cpu().numpy()
    radii_cpu = radii.detach().float().cpu().numpy()
    importance_cpu = importance.detach().float().cpu().numpy()
    valid = (
        np.isfinite(uv_cpu).all(axis=1)
        & np.isfinite(depth_cpu)
        & (depth_cpu > 0)
        & (radii_cpu > 0)
    )
    valid_indices = np.flatnonzero(valid)
    losers = np.zeros(len(uv_cpu), dtype=bool)
    if len(valid_indices) < 2:
        return torch.from_numpy(losers).to(device=device)

    valid_uv = uv_cpu[valid_indices]
    neighbor_count = min(max_neighbors + 1, len(valid_indices))
    _, neighbors = cKDTree(valid_uv).query(valid_uv, k=neighbor_count, workers=-1)
    if neighbor_count == 1:
        return torch.from_numpy(losers).to(device=device)
    if neighbors.ndim == 1:
        neighbors = neighbors[:, np.newaxis]
    candidate_cpu = None
    if candidate_mask is not None:
        candidate_cpu = candidate_mask.detach().cpu().numpy().astype(bool)

    for local_index, nearby in enumerate(neighbors):
        point_index = valid_indices[local_index]
        if candidate_cpu is not None and not candidate_cpu[point_index]:
            continue
        nearby = nearby[nearby != local_index]
        if not len(nearby):
            continue
        neighbor_indices = valid_indices[nearby]
        center_distance = np.linalg.norm(
            valid_uv[local_index] - uv_cpu[neighbor_indices], axis=1,
        )
        overlap = center_distance <= (radii_cpu[point_index] + radii_cpu[neighbor_indices])
        tolerance = depth_absolute_tolerance + depth_relative_tolerance * np.minimum(
            depth_cpu[point_index], depth_cpu[neighbor_indices],
        )
        depth_consistent = np.abs(depth_cpu[point_index] - depth_cpu[neighbor_indices]) <= tolerance
        dominated = importance_cpu[neighbor_indices] >= dominance_ratio * importance_cpu[point_index]
        losers[point_index] = bool(np.any(overlap & depth_consistent & dominated))
    return torch.from_numpy(losers).to(device=device)


def select_prune_candidates(candidates, importance, max_prune_ratio, xyz=None, voxel_size=None, max_voxel_prune_ratio=1.0):
    limit = int(importance.numel() * max_prune_ratio)
    prune_mask = torch.zeros_like(candidates)
    candidate_indices = candidates.nonzero(as_tuple=False).flatten()
    if limit <= 0 or not len(candidate_indices):
        return prune_mask

    order = torch.argsort(importance[candidate_indices])
    ordered_indices = candidate_indices[order]
    if xyz is None or voxel_size is None or voxel_size <= 0 or max_voxel_prune_ratio >= 1.0:
        selected = ordered_indices[:limit]
        prune_mask[selected] = True
        return prune_mask
    if not 0.0 < max_voxel_prune_ratio <= 1.0:
        raise ValueError("max_voxel_prune_ratio must be in (0, 1]")

    voxel_coordinates = torch.floor(xyz.detach().float().cpu() / voxel_size).to(torch.int64)
    _, inverse, voxel_population = torch.unique(
        voxel_coordinates, dim=0, return_inverse=True, return_counts=True,
    )
    voxel_limit = torch.clamp(
        torch.floor(voxel_population.float() * max_voxel_prune_ratio).to(torch.long),
        min=1,
    )
    selected_per_voxel = torch.zeros_like(voxel_limit)
    selected = []
    for point_index in ordered_indices.detach().cpu().tolist():
        voxel_index = int(inverse[point_index].item())
        if selected_per_voxel[voxel_index] >= voxel_limit[voxel_index]:
            continue
        selected.append(point_index)
        selected_per_voxel[voxel_index] += 1
        if len(selected) == limit:
            break
    if selected:
        prune_mask[torch.tensor(selected, device=prune_mask.device)] = True
    return prune_mask


def build_geometric_prune_decision(
    importance,
    visibility_count,
    support_count,
    depth_conflict_count,
    isolated,
    max_prune_ratio,
    importance_quantile,
    screen_overlap_count=None,
    min_overlap_views=3,
    xyz=None,
    voxel_size=None,
    max_voxel_prune_ratio=1.0,
):
    if not 0.0 <= max_prune_ratio <= 0.03:
        raise ValueError("max_prune_ratio must be in [0, 0.03]")
    if not 0.0 < importance_quantile < 1.0:
        raise ValueError("importance_quantile must be in (0, 1)")

    threshold = torch.quantile(importance, importance_quantile)
    low_importance = importance <= threshold
    no_support = support_count == 0
    if screen_overlap_count is None:
        screen_overlap_count = torch.zeros_like(visibility_count)
    geometric_redundant = no_support & (depth_conflict_count >= 2)
    overlap_redundant = screen_overlap_count >= min_overlap_views
    redundant = low_importance & (geometric_redundant | overlap_redundant)
    floater = low_importance & no_support & isolated & (visibility_count <= 2)
    candidates = redundant | floater
    prune_mask = select_prune_candidates(
        candidates, importance, max_prune_ratio, xyz, voxel_size, max_voxel_prune_ratio,
    )

    return {
        "importance": importance,
        "low_importance": low_importance,
        "no_support": no_support,
        "geometric_redundant": geometric_redundant,
        "screen_overlap_count": screen_overlap_count,
        "overlap_redundant": overlap_redundant,
        "redundant": redundant,
        "floater": floater,
        "prune_mask": prune_mask,
        "importance_threshold": threshold,
    }
