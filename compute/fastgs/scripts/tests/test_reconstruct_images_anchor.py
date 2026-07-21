from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))

from reconstruct_images import calculate_anchor, anchor_json


def pose_looking_at(origin, target):
    origin = np.asarray(origin, dtype=float)
    target = np.asarray(target, dtype=float)
    forward = target - origin
    forward /= np.linalg.norm(forward)
    up = np.array([0.0, 1.0, 0.0])
    right = np.cross(up, forward)
    right /= np.linalg.norm(right)
    camera_up = np.cross(forward, right)
    pose = np.eye(4)
    pose[:3, :3] = np.column_stack([right, camera_up, forward])
    pose[:3, 3] = origin
    return pose


def test_calculate_anchor_prefers_robust_ray_intersection():
    target = np.array([0.2, -0.1, 2.0])
    poses = [
        pose_looking_at([-1.0, 0.0, 0.0], target),
        pose_looking_at([1.0, 0.2, 0.0], target),
        pose_looking_at([0.0, -1.0, 0.5], target),
        pose_looking_at([0.0, 1.0, 0.3], target),
    ]

    method, anchor = calculate_anchor(poses, point_cloud_center=np.array([9.0, 9.0, 9.0]))

    assert method == "robust_ray_intersection"
    np.testing.assert_allclose(anchor, target, atol=1e-5)


def test_calculate_anchor_falls_back_to_point_cloud_center_for_parallel_rays():
    poses = [
        pose_looking_at([-1.0, 0.0, 0.0], [0.0, 0.0, 1.0]),
        pose_looking_at([1.0, 0.0, 0.0], [1.0, 0.0, 1.0]),
    ]
    method, anchor = calculate_anchor(poses, point_cloud_center=np.array([2.0, 3.0, 4.0]))

    assert method == "point_cloud_bbox_center"
    np.testing.assert_allclose(anchor, [2.0, 3.0, 4.0])


def test_anchor_json_records_method_and_coordinates():
    import json

    output = anchor_json("camera_position_centroid", np.array([1.25, -2.5, 3.75]))
    payload = json.loads(output)

    assert payload["method"] == "camera_position_centroid"
    assert payload["coordinate_system"] == "colmap_world"
    assert payload["position"] == {"x": 1.25, "y": -2.5, "z": 3.75}
