import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from align_colmap import align_colmap_model  # noqa: E402
from colmap_model_io import (  # noqa: E402
    CameraRecord,
    ImageRecord,
    Point3DRecord,
    read_images_binary,
    read_points3d_binary,
    write_cameras_binary,
    write_images_binary,
    write_points3d_binary,
)


def write_model(root, image_name="frame_000000.jpg"):
    model = root / "sparse" / "0"
    model.mkdir(parents=True)
    write_cameras_binary(model / "cameras.bin", {
        1: CameraRecord(1, 4, 640, 480, np.array([500., 500., 320., 240., 0., 0., 0., 0.])),
    })
    write_images_binary(model / "images.bin", {
        1: ImageRecord(1, np.array([1., 0., 0., 0.]), np.array([1., 2., 3.]), 1, image_name, np.array([[10., 20.]]), np.array([1], dtype=np.int64)),
    })
    write_points3d_binary(model / "points3D.bin", {
        1: Point3DRecord(1, np.array([1., 2., 3.]), np.array([10, 20, 30], dtype=np.uint8), .1, np.array([1], dtype=np.int32), np.array([0], dtype=np.int32)),
    })
    (root / "images").mkdir()
    (root / "images" / image_name).write_bytes(b"image")
    return model


def write_manifest(path, acceleration):
    path.write_text(json.dumps({
        "version": 1,
        "acceleration_frame": "camera",
        "acceleration_type": "gravity",
        "frames": [{"image": "frame_000000.jpg", "timestamp_ms": 0, "acceleration": acceleration}],
    }), encoding="utf-8")


def test_align_colmap_model_writes_new_directory_and_rotates_model(tmp_path):
    raw = tmp_path / "colmap_raw"
    write_model(raw)
    manifest = tmp_path / "imu_manifest.json"
    write_manifest(manifest, [0., 0., 9.81])
    output = tmp_path / "colmap_gravity_aligned"

    metadata = align_colmap_model(raw, manifest, output)

    assert metadata["coordinate_system"] == "gravity_aligned_world"
    assert output != raw and (output / "sparse" / "0" / "images.bin").is_file()
    image = read_images_binary(output / "sparse" / "0" / "images.bin")[1]
    point = read_points3d_binary(output / "sparse" / "0" / "points3D.bin")[1]
    np.testing.assert_allclose(image.tvec, [1., 2., 3.])
    # rotation_to_target uses the minimum-angle proper rotation from +Z to +Y.
    np.testing.assert_allclose(point.xyz, [1., 3., -2.])
    assert read_points3d_binary(raw / "sparse" / "0" / "points3D.bin")[1].xyz.tolist() == [1., 2., 3.]


def test_align_colmap_model_fails_strictly_without_matching_imu(tmp_path):
    raw = tmp_path / "colmap_raw"
    write_model(raw)
    manifest = tmp_path / "imu_manifest.json"
    write_manifest(manifest, [0., 0., 0.])

    with pytest.raises(ValueError, match="no valid matched IMU"):
        align_colmap_model(raw, manifest, tmp_path / "aligned")
