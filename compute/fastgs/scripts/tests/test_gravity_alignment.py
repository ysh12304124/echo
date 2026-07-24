import json
import sys
from pathlib import Path

import numpy as np
import pytest
from plyfile import PlyData, PlyElement

sys.path.insert(0, str(Path(__file__).parents[1]))

from gravity_alignment import (  # noqa: E402
    ManifestError,
    estimate_gravity,
    load_manifest,
    rotation_to_target,
    transform_gaussian_ply,
    transform_pose_text,
    transform_poses,
)


def manifest_with_frames(items, acceleration_type="gravity"):
    return {
        "version": 1,
        "acceleration_frame": "camera",
        "acceleration_type": acceleration_type,
        "frames": [
            {
                "image": image,
                "timestamp_ms": index * 33,
                "acceleration": acceleration,
            }
            for index, (image, acceleration) in enumerate(items)
        ],
    }


def write_manifest(tmp_path, items, acceleration_type="gravity"):
    path = tmp_path / "imu_manifest.json"
    path.write_text(
        json.dumps(manifest_with_frames(items, acceleration_type)),
        encoding="utf-8",
    )
    return path


def test_load_manifest_associates_acceleration_by_image(tmp_path):
    path = write_manifest(tmp_path, [("frame_000000.jpg", [0.0, 0.0, 9.81])])

    manifest = load_manifest(path)

    assert manifest.acceleration_type == "gravity"
    assert manifest.frames["frame_000000.jpg"].acceleration == (0.0, 0.0, 9.81)


def test_load_manifest_rejects_missing_or_invalid_structure(tmp_path):
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "missing.json")

    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"version": 2}), encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(path)


def test_load_manifest_ignores_duplicate_and_invalid_entries(tmp_path):
    path = tmp_path / "imu_manifest.json"
    path.write_text(
        json.dumps({
            "version": 1,
            "acceleration_frame": "camera",
            "acceleration_type": "gravity",
            "frames": [
                {"image": "a.jpg", "timestamp_ms": 1, "acceleration": [0, 0, 9.81]},
                {"image": "a.jpg", "timestamp_ms": 2, "acceleration": [0, 1, 0]},
                {"image": "bad.jpg", "timestamp_ms": 3, "acceleration": [0, 0]},
                {"image": "nan.jpg", "timestamp_ms": 4, "acceleration": [0, 0, "nan"]},
            ],
        }),
        encoding="utf-8",
    )

    manifest = load_manifest(path)

    assert list(manifest.frames) == ["a.jpg"]
    assert manifest.frames["a.jpg"].timestamp_ms == 1


def test_rotation_to_target_maps_sixty_degree_tilt_to_positive_y():
    source = np.array([0.0, np.sqrt(3.0) / 2.0, 0.5])

    rotation = rotation_to_target(source, np.array([0.0, 1.0, 0.0]))

    np.testing.assert_allclose(rotation @ source, [0.0, 1.0, 0.0], atol=1e-7)
    np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-7)
    assert np.linalg.det(rotation) == pytest.approx(1.0)


def test_rotation_to_target_handles_opposite_vectors_deterministically():
    rotation = rotation_to_target(np.array([0.0, -1.0, 0.0]), np.array([0.0, 1.0, 0.0]))

    np.testing.assert_allclose(rotation @ [0.0, -1.0, 0.0], [0.0, 1.0, 0.0])
    np.testing.assert_allclose(rotation, np.diag([1.0, -1.0, -1.0]))


def test_estimate_gravity_aligns_consistent_camera_vectors(tmp_path):
    names = ["a.jpg", "b.jpg", "c.jpg"]
    manifest = load_manifest(write_manifest(
        tmp_path,
        [(name, [0.0, 0.0, 9.81]) for name in names],
    ))
    poses = {name: np.eye(4) for name in names}

    result = estimate_gravity(manifest, poses, names)

    assert result.method == "gravity_aligned_world"
    assert result.coordinate_system == "gravity_aligned_world"
    np.testing.assert_allclose(result.gravity_colmap, [0.0, 0.0, 1.0], atol=1e-7)
    np.testing.assert_allclose(result.rotation @ result.gravity_colmap, [0.0, 1.0, 0.0], atol=1e-7)


def test_estimate_gravity_inverts_specific_force(tmp_path):
    names = ["a.jpg", "b.jpg", "c.jpg"]
    path = tmp_path / "imu_manifest.json"
    path.write_text(
        json.dumps(manifest_with_frames(
            [(name, [0.0, 0.0, -9.81]) for name in names],
            "specific_force",
        )),
        encoding="utf-8",
    )
    manifest = load_manifest(path)

    result = estimate_gravity(manifest, {name: np.eye(4) for name in names}, names)

    assert result.method == "gravity_aligned_world"
    np.testing.assert_allclose(result.gravity_colmap, [0.0, 0.0, 1.0], atol=1e-7)


def test_estimate_gravity_rejects_unstable_or_insufficient_samples(tmp_path):
    names = ["a.jpg", "b.jpg"]
    manifest = load_manifest(write_manifest(
        tmp_path,
        [("a.jpg", [0.0, 0.0, 9.81]), ("b.jpg", [0.0, 9.81, 0.0])],
    ))

    result = estimate_gravity(manifest, {name: np.eye(4) for name in names}, names)

    assert result.method == "colmap_world"
    assert result.coordinate_system == "colmap_world"
    np.testing.assert_allclose(result.rotation, np.eye(3))


def test_estimate_gravity_uses_robust_inliers(tmp_path):
    names = ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "outlier.jpg"]
    items = [(name, [0.0, 0.0, 9.81]) for name in names[:4]]
    items.append(("outlier.jpg", [9.81, 0.0, 0.0]))
    manifest = load_manifest(write_manifest(tmp_path, items))

    result = estimate_gravity(manifest, {name: np.eye(4) for name in names}, names)

    assert result.method == "gravity_aligned_world"
    np.testing.assert_allclose(result.gravity_colmap, [0.0, 0.0, 1.0], atol=1e-7)
    assert result.valid_sample_count == 4


def write_synthetic_gaussian_ply(path):
    dtype = [
        (name, "f4")
        for name in (
            "x", "y", "z", "nx", "ny", "nz",
            "f_dc_0", "f_dc_1", "f_dc_2",
            "f_rest_0", "f_rest_1", "f_rest_2",
            "opacity", "scale_0", "scale_1", "scale_2",
            "rot_0", "rot_1", "rot_2", "rot_3",
        )
    ]
    values = np.zeros(2, dtype=dtype)
    values["x"] = [1.0, -2.0]
    values["y"] = [2.0, 3.0]
    values["z"] = [4.0, -5.0]
    values["nx"] = [0.1, 0.2]
    values["f_dc_0"] = [0.3, 0.4]
    values["f_rest_1"] = [0.5, 0.6]
    values["opacity"] = [0.7, 0.8]
    values["scale_0"] = [0.9, 1.0]
    values["scale_1"] = [1.1, 1.2]
    values["scale_2"] = [1.3, 1.4]
    values["rot_0"] = [1.0, np.sqrt(0.5)]
    values["rot_1"] = [0.0, 0.0]
    values["rot_2"] = [0.0, 0.0]
    values["rot_3"] = [0.0, np.sqrt(0.5)]
    PlyData(
        [PlyElement.describe(values, "vertex")],
        text=False,
        byte_order="<",
    ).write(str(path))
    return path


def read_vertex_arrays(path):
    return PlyData.read(str(path))["vertex"].data.copy()


def test_transform_poses_rotates_c2w_rotation_and_translation():
    poses = {"frame.jpg": np.array([
        [1.0, 0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0, 2.0],
        [0.0, 0.0, 1.0, 3.0],
        [0.0, 0.0, 0.0, 1.0],
    ])}
    rotation = rotation_to_target(np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0]))

    transformed = transform_poses(poses, rotation)

    np.testing.assert_allclose(transformed["frame.jpg"][:3, :3], rotation)
    np.testing.assert_allclose(transformed["frame.jpg"][:3, 3], rotation @ [1.0, 2.0, 3.0])


def test_transform_pose_text_preserves_row_major_c2w_format():
    text = "1 0 0 1 0 1 0 2 0 0 1 3 0 0 0 1\n"
    rotation = rotation_to_target(np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0]))

    transformed = transform_pose_text(text, rotation)
    matrix = np.asarray([float(value) for value in transformed.split()]).reshape(4, 4)

    np.testing.assert_allclose(matrix[:3, :3], rotation)
    np.testing.assert_allclose(matrix[:3, 3], rotation @ [1.0, 2.0, 3.0])


def test_transform_gaussian_ply_changes_only_position_and_wxyz_rotation(tmp_path):
    ply_path = write_synthetic_gaussian_ply(tmp_path / "point_cloud.ply")
    before = read_vertex_arrays(ply_path)
    rotation = rotation_to_target(np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0]))

    transform_gaussian_ply(ply_path, rotation)

    after = read_vertex_arrays(ply_path)
    before_positions = np.column_stack([before[name] for name in ("x", "y", "z")])
    expected_positions = (rotation @ before_positions.T).T
    np.testing.assert_allclose(after["x"], expected_positions[:, 0])
    np.testing.assert_allclose(after["y"], expected_positions[:, 1])
    np.testing.assert_allclose(after["z"], expected_positions[:, 2])
    for name in before.dtype.names:
        if name not in {"x", "y", "z", "rot_0", "rot_1", "rot_2", "rot_3"}:
            np.testing.assert_array_equal(after[name], before[name])
    assert len(after) == len(before)

    for index in range(len(after)):
        quaternion = np.array([
            after["rot_0"][index], after["rot_1"][index],
            after["rot_2"][index], after["rot_3"][index],
        ])
        assert np.linalg.norm(quaternion) == pytest.approx(1.0, abs=1e-6)


def test_transform_gaussian_ply_identity_preserves_semantic_values(tmp_path):
    ply_path = write_synthetic_gaussian_ply(tmp_path / "point_cloud.ply")
    before = read_vertex_arrays(ply_path)

    transform_gaussian_ply(ply_path, np.eye(3))

    after = read_vertex_arrays(ply_path)
    for name in before.dtype.names:
        np.testing.assert_array_equal(after[name], before[name])
