#!/usr/bin/env python3
"""Generate camera-frame gravity samples for deterministic huiyi validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from colmap_model_io import read_images_binary


def _qvec_to_rotation_w2c(qvec: np.ndarray) -> np.ndarray:
    w, x, y, z = np.asarray(qvec, dtype=float) / np.linalg.norm(qvec)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def write_synthetic_manifest(
    images_path: Path,
    input_dir: Path,
    output_path: Path,
    start_timestamp_ms: int = 1_000,
    fps: float = 15.0,
    gravity_world: tuple[float, float, float] = (0.0, 1.0, 0.0),
) -> dict[str, int]:
    images = read_images_binary(images_path)
    by_name = {record.name: record for record in images.values()}
    frame_paths = sorted(
        path for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
    )
    gravity = np.asarray(gravity_world, dtype=float)
    if not np.isfinite(gravity).all() or np.linalg.norm(gravity) <= 1e-9:
        raise ValueError("gravity_world must be finite and non-zero")

    entries = []
    for index, path in enumerate(frame_paths):
        image = by_name.get(path.name)
        if image is None:
            continue
        acceleration = _qvec_to_rotation_w2c(image.qvec) @ gravity
        entries.append({
            "image": path.name,
            "timestamp_ms": int(round(start_timestamp_ms + index * 1000.0 / fps)),
            "acceleration": [float(value) for value in acceleration],
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "version": 1,
        "acceleration_frame": "camera",
        "acceleration_type": "gravity",
        "frames": entries,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"frame_count": len(frame_paths), "matched_count": len(entries)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images-bin", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-timestamp-ms", type=int, default=1_000)
    parser.add_argument("--fps", type=float, default=15.0)
    args = parser.parse_args()
    print(write_synthetic_manifest(
        args.images_bin, args.input_dir, args.output,
        start_timestamp_ms=args.start_timestamp_ms, fps=args.fps,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
