import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from anchor_calculator import calculate_anchor  # noqa: E402


def pose(center, forward):
    matrix = np.eye(4, dtype=float)
    matrix[:3, 3] = center
    matrix[:3, 2] = np.asarray(forward, dtype=float)
    return matrix


def test_calculate_anchor_prefers_robust_ray_intersection():
    poses = [
        pose([1., 0., 0.], [-1., 0., 1.]),
        pose([-1., 0., 0.], [1., 0., 1.]),
        pose([0., 1., 0.], [0., -1., 1.]),
    ]

    method, anchor = calculate_anchor(poses, np.array([99., 99., 99.]))

    assert method == "robust_ray_intersection"
    np.testing.assert_allclose(anchor, [0., 0., 1.], atol=1e-6)


def test_calculate_anchor_falls_back_to_point_cloud_center():
    poses = [pose([0., 0., 0.], [0., 0., 1.]), pose([1., 0., 0.], [0., 0., 1.])]

    method, anchor = calculate_anchor(poses, np.array([2., 3., 4.]))

    assert method == "point_cloud_bbox_center"
    np.testing.assert_allclose(anchor, [2., 3., 4.])


def test_calculate_anchor_falls_back_to_camera_centroid():
    poses = [pose([0., 0., 0.], [0., 0., 1.]), pose([2., 4., 6.], [0., 0., 1.])]

    method, anchor = calculate_anchor(poses, None)

    assert method == "camera_position_centroid"
    np.testing.assert_allclose(anchor, [1., 2., 3.])


def test_calculate_anchor_rejects_empty_pose_list():
    with pytest.raises(ValueError, match="NO_REGISTERED_POSES"):
        calculate_anchor([], None)
