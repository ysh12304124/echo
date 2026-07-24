import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from colmap_model_io import (  # noqa: E402
    CameraRecord,
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


def synthetic_model():
    cameras = {
        7: CameraRecord(
            camera_id=7,
            model_id=4,
            width=640,
            height=480,
            params=np.array([500.0, 500.0, 320.0, 240.0, 0.01, 0.02, 0.0, 0.0]),
        ),
    }
    images = {
        10: ImageRecord(
            image_id=10,
            qvec=np.array([1.0, 0.0, 0.0, 0.0]),
            tvec=np.array([1.0, 2.0, 3.0]),
            camera_id=7,
            name="frame_000000.jpg",
            xys=np.array([[10.5, 20.5], [30.0, 40.0]]),
            point3d_ids=np.array([100, -1], dtype=np.int64),
        ),
        11: ImageRecord(
            image_id=11,
            qvec=np.array([0.9238795, 0.0, 0.3826834, 0.0]),
            tvec=np.array([-1.0, 0.5, 2.0]),
            camera_id=7,
            name="frame_000001.jpg",
            xys=np.array([[5.0, 8.0]]),
            point3d_ids=np.array([100], dtype=np.int64),
        ),
    }
    points = {
        100: Point3DRecord(
            point3d_id=100,
            xyz=np.array([1.25, -2.5, 3.75]),
            rgb=np.array([12, 34, 56], dtype=np.uint8),
            error=0.125,
            image_ids=np.array([10, 11], dtype=np.int32),
            point2d_idxs=np.array([0, 0], dtype=np.int32),
        ),
        101: Point3DRecord(
            point3d_id=101,
            xyz=np.array([-1.0, 0.0, 2.0]),
            rgb=np.array([255, 128, 1], dtype=np.uint8),
            error=1.5,
            image_ids=np.array([], dtype=np.int32),
            point2d_idxs=np.array([], dtype=np.int32),
        ),
    }
    return cameras, images, points


def test_colmap_binary_model_round_trip(tmp_path):
    cameras, images, points = synthetic_model()
    camera_path = tmp_path / "cameras.bin"
    image_path = tmp_path / "images.bin"
    points_path = tmp_path / "points3D.bin"

    write_cameras_binary(camera_path, cameras)
    write_images_binary(image_path, images)
    write_points3d_binary(points_path, points)

    actual_cameras = read_cameras_binary(camera_path)
    actual_images = read_images_binary(image_path)
    actual_points = read_points3d_binary(points_path)

    assert actual_cameras.keys() == cameras.keys()
    assert actual_images.keys() == images.keys()
    assert actual_points.keys() == points.keys()
    np.testing.assert_allclose(actual_cameras[7].params, cameras[7].params)
    for image_id, expected in images.items():
        actual = actual_images[image_id]
        np.testing.assert_allclose(actual.qvec, expected.qvec)
        np.testing.assert_allclose(actual.tvec, expected.tvec)
        np.testing.assert_allclose(actual.xys, expected.xys)
        np.testing.assert_array_equal(actual.point3d_ids, expected.point3d_ids)
        assert actual.name == expected.name
    for point_id, expected in points.items():
        actual = actual_points[point_id]
        np.testing.assert_allclose(actual.xyz, expected.xyz)
        np.testing.assert_array_equal(actual.rgb, expected.rgb)
        np.testing.assert_allclose(actual.error, expected.error)
        np.testing.assert_array_equal(actual.image_ids, expected.image_ids)
        np.testing.assert_array_equal(actual.point2d_idxs, expected.point2d_idxs)


def test_validate_colmap_model_reports_counts(tmp_path):
    cameras, images, points = synthetic_model()
    model_dir = tmp_path / "sparse" / "0"
    model_dir.mkdir(parents=True)
    write_cameras_binary(model_dir / "cameras.bin", cameras)
    write_images_binary(model_dir / "images.bin", images)
    write_points3d_binary(model_dir / "points3D.bin", points)

    metrics = validate_colmap_model(model_dir)

    assert metrics.camera_count == 1
    assert metrics.registered_image_count == 2
    assert metrics.point3d_count == 2


def test_validate_colmap_model_rejects_missing_file(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    with pytest.raises(ValueError, match="points3D.bin"):
        validate_colmap_model(model_dir)
