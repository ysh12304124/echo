import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from run_fastgs import build_fastgs_commands, find_trained_ply, validate_fastgs_scene  # noqa: E402
from colmap_model_io import CameraRecord, ImageRecord, write_cameras_binary, write_images_binary, write_points3d_binary  # noqa: E402


def write_valid_scene(scene):
    (scene / "images").mkdir(parents=True)
    model = scene / "sparse" / "0"
    model.mkdir(parents=True)
    write_cameras_binary(model / "cameras.bin", {1: CameraRecord(1, 1, 640, 480, np.array([500., 500., 320., 240.]))})
    write_images_binary(model / "images.bin", {1: ImageRecord(1, np.array([1., 0., 0., 0.]), np.zeros(3), 1, "frame.jpg", np.empty((0, 2)), np.empty((0,), dtype=np.int64))})
    write_points3d_binary(model / "points3D.bin", {})


def test_validate_fastgs_scene_requires_aligned_colmap_model(tmp_path):
    scene = tmp_path / "colmap_gravity_aligned"
    write_valid_scene(scene)

    validate_fastgs_scene(scene)


def test_validate_fastgs_scene_rejects_missing_model_file(tmp_path):
    scene = tmp_path / "scene"
    write_valid_scene(scene)
    (scene / "sparse" / "0" / "points3D.bin").unlink()
    with pytest.raises(ValueError, match="points3D.bin"):
        validate_fastgs_scene(scene)


def test_build_fastgs_commands_use_selected_scene_and_model(tmp_path):
    commands = build_fastgs_commands(
        scene_dir=tmp_path / "colmap_gravity_aligned",
        model_dir=tmp_path / "fastgs_model",
        fastgs_dir=Path("/repo/FastGS"),
        iterations=30000,
        python_executable="python3",
    )

    assert len(commands) == 1
    assert str(Path("/repo/FastGS") / "train.py") in commands[0]
    assert str(tmp_path / "colmap_gravity_aligned") in commands[0]
    assert str(tmp_path / "fastgs_model") in commands[0]
    assert "30000" in commands[0]


def test_find_trained_ply_rejects_empty_or_missing_output(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        find_trained_ply(tmp_path / "model", 30000)
    ply = tmp_path / "model" / "point_cloud" / "iteration_30000" / "point_cloud.ply"
    ply.parent.mkdir(parents=True)
    ply.write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        find_trained_ply(tmp_path / "model", 30000)
