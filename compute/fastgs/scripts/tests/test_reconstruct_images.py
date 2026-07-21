import json
import sys
from pathlib import Path

import numpy as np
import pytest
from plyfile import PlyData, PlyElement

sys.path.insert(0, str(Path(__file__).parents[1]))

from gravity_alignment import apply_gravity_alignment  # noqa: E402
from reconstruct_images import anchor_json  # noqa: E402


def write_manifest(path, names, acceleration):
    path.write_text(json.dumps({
        "version": 1,
        "acceleration_frame": "camera",
        "acceleration_type": "gravity",
        "frames": [
            {"image": name, "timestamp_ms": index, "acceleration": acceleration}
            for index, name in enumerate(names)
        ],
    }))


def write_gaussian_ply(path):
    names = (
        "x", "y", "z", "nx", "ny", "nz",
        "f_dc_0", "f_dc_1", "f_dc_2", "f_rest_0",
        "opacity", "scale_0", "scale_1", "scale_2",
        "rot_0", "rot_1", "rot_2", "rot_3",
    )
    values = np.zeros(1, dtype=[(name, "f4") for name in names])
    values["x"] = [1.0]
    values["y"] = [2.0]
    values["z"] = [3.0]
    values["rot_0"] = [1.0]
    PlyData([PlyElement.describe(values, "vertex")], text=False, byte_order="<").write(str(path))


def test_anchor_json_accepts_gravity_aligned_coordinate_system():
    payload = json.loads(anchor_json(
        "camera_position_centroid",
        np.array([1.0, 2.0, 3.0]),
        coordinate_system="gravity_aligned_world",
    ))

    assert payload["coordinate_system"] == "gravity_aligned_world"


def test_apply_gravity_alignment_missing_manifest_returns_colmap_fallback(tmp_path):
    poses = tmp_path / "poses.txt"
    poses.write_text("1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1\n")
    ply = tmp_path / "point_cloud.ply"
    write_gaussian_ply(ply)

    result = apply_gravity_alignment(
        manifest_path=tmp_path / "imu_manifest.json",
        poses_path=poses,
        ply_path=ply,
        image_names=["frame_000000.jpg"],
    )

    assert result.method == "colmap_world"
    assert result.coordinate_system == "colmap_world"


def test_apply_gravity_alignment_success_reports_gravity_world(tmp_path):
    names = ["a.jpg", "b.jpg", "c.jpg"]
    manifest = tmp_path / "imu_manifest.json"
    write_manifest(manifest, names, [0.0, 0.0, 9.81])
    poses = tmp_path / "poses.txt"
    poses.write_text("\n".join(
        "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1" for _ in names
    ) + "\n")
    ply = tmp_path / "point_cloud.ply"
    write_gaussian_ply(ply)

    result = apply_gravity_alignment(
        manifest_path=manifest,
        poses_path=poses,
        ply_path=ply,
        image_names=names,
    )

    assert result.method == "gravity_aligned_world"
    assert result.coordinate_system == "gravity_aligned_world"
