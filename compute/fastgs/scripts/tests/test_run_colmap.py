import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from colmap_model_io import CameraRecord, ImageRecord, Point3DRecord, write_cameras_binary, write_images_binary, write_points3d_binary  # noqa: E402
from run_colmap import build_colmap_command, inspect_colmap_registration  # noqa: E402


def write_model(model_dir, registered_names):
    model_dir.mkdir(parents=True, exist_ok=True)
    write_cameras_binary(model_dir / "cameras.bin", {
        1: CameraRecord(1, 4, 640, 480, np.array([500., 500., 320., 240., 0., 0., 0., 0.])),
    })
    images = {
        index + 1: ImageRecord(
            index + 1,
            np.array([1., 0., 0., 0.]),
            np.zeros(3),
            1,
            name,
            np.empty((0, 2)),
            np.empty((0,), dtype=np.int64),
        )
        for index, name in enumerate(registered_names)
    }
    write_images_binary(model_dir / "images.bin", images)
    write_points3d_binary(model_dir / "points3D.bin", {})


def test_inspect_registration_accepts_exactly_eighty_percent(tmp_path):
    names = [f"frame_{index:06d}.jpg" for index in range(10)]
    write_model(tmp_path, names[:8])

    metrics = inspect_colmap_registration(tmp_path, names)

    assert metrics.input_image_count == 10
    assert metrics.registered_image_count == 8
    assert metrics.registration_ratio == pytest.approx(0.8)
    assert metrics.unregistered_images == names[8:]
    assert metrics.status == "completed_with_warnings"


def test_inspect_registration_rejects_below_eighty_percent(tmp_path):
    names = [f"frame_{index:06d}.jpg" for index in range(10)]
    write_model(tmp_path, names[:7])

    metrics = inspect_colmap_registration(tmp_path, names)

    assert metrics.status == "failed"
    assert metrics.error_code == "LOW_REGISTRATION_RATIO"


def test_build_colmap_command_uses_stage_output_as_source(tmp_path):
    command = build_colmap_command(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "colmap_raw",
        fastgs_dir=Path("/repo/FastGS"),
        colmap_executable="/opt/colmap",
        python_executable="python3",
        feature_gpu=False,
        mapper_gpu=True,
    )

    assert str(Path("/repo/FastGS") / "convert.py") in command
    assert command[command.index("--source_path") + 1] == str(tmp_path / "colmap_raw")
    assert "--colmap_new_api" in command
    assert "--no_gpu" in command
    assert "--mapper_use_gpu" in command
