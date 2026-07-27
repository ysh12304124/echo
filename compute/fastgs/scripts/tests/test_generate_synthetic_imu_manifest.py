import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))

from colmap_model_io import ImageRecord
from generate_synthetic_imu_manifest import write_synthetic_manifest


def test_synthetic_manifest_projects_world_gravity_into_camera_frame(tmp_path, monkeypatch):
    frame_dir = tmp_path / "input"
    frame_dir.mkdir()
    (frame_dir / "frame_000001.jpg").write_bytes(b"jpeg")
    (frame_dir / "frame_000002.jpg").write_bytes(b"jpeg")
    images = {
        1: ImageRecord(1, np.array([1.0, 0.0, 0.0, 0.0]), np.zeros(3), 1, "frame_000001.jpg", np.empty((0, 2)), np.empty((0,), dtype=np.int64)),
        2: ImageRecord(2, np.array([1.0, 0.0, 0.0, 0.0]), np.zeros(3), 1, "frame_000002.jpg", np.empty((0, 2)), np.empty((0,), dtype=np.int64)),
    }
    monkeypatch.setattr("generate_synthetic_imu_manifest.read_images_binary", lambda _path: images)

    output = tmp_path / "imu_manifest.json"
    stats = write_synthetic_manifest(
        tmp_path / "images.bin", frame_dir, output, start_timestamp_ms=1000, fps=10.0
    )

    assert stats == {"frame_count": 2, "matched_count": 2}
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["frames"][0]["acceleration"] == [0.0, 1.0, 0.0]
