import json
import sys
from pathlib import Path

import numpy as np
from plyfile import PlyData, PlyElement

sys.path.insert(0, str(Path(__file__).parents[1]))

from colmap_model_io import CameraRecord, ImageRecord, write_cameras_binary, write_images_binary  # noqa: E402
from export_outputs import export_outputs  # noqa: E402


def test_export_outputs_writes_json_and_reports_unregistered_images(tmp_path):
    aligned = tmp_path / "colmap_gravity_aligned"
    model = aligned / "sparse" / "0"
    model.mkdir(parents=True)
    (aligned / "images").mkdir()
    write_cameras_binary(model / "cameras.bin", {1: CameraRecord(1, 1, 640, 480, np.array([500., 500., 320., 240.]))})
    write_images_binary(model / "images.bin", {
        1: ImageRecord(1, np.array([1., 0., 0., 0.]), np.array([0., 0., 0.]), 1, "frame_000000.jpg", np.empty((0, 2)), np.empty((0,), dtype=np.int64)),
        2: ImageRecord(2, np.array([1., 0., 0., 0.]), np.array([-1., 0., 0.]), 1, "frame_000001.jpg", np.empty((0, 2)), np.empty((0,), dtype=np.int64)),
    })
    (aligned / "alignment_meta.json").write_text(json.dumps({"coordinate_system": "gravity_aligned_world"}), encoding="utf-8")
    ply = tmp_path / "trained.ply"
    values = np.zeros(1, dtype=[("x", "f4"), ("y", "f4"), ("z", "f4")])
    PlyData([PlyElement.describe(values, "vertex")], text=False).write(str(ply))
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for name in ("frame_000000.jpg", "frame_000001.jpg", "frame_000002.jpg"):
        (input_dir / name).write_bytes(b"image")

    outputs = export_outputs(aligned, ply, input_dir, tmp_path / "outputs")

    poses = json.loads((outputs / "poses.json").read_text(encoding="utf-8"))
    assert poses["registered_image_count"] == 2
    assert poses["unregistered_images"] == ["frame_000002.jpg"]
    assert poses["coordinate_system"] == "gravity_aligned_world"
    assert len(poses["poses"]) == 2
    assert len((outputs / "poses.txt").read_text(encoding="utf-8").splitlines()) == 2
    assert json.loads((outputs / "anchor.json").read_text(encoding="utf-8"))["coordinate_system"] == "gravity_aligned_world"
