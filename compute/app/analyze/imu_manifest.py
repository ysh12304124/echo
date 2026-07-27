"""Build the versioned FastGS image-to-acceleration manifest from IMU JSONL."""

from __future__ import annotations

import bisect
import json
import math
from pathlib import Path
from typing import Any


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _load_acceleration_samples(imu_path: Path | None) -> list[tuple[int, tuple[float, float, float]]]:
    if imu_path is None or not imu_path.is_file():
        return []

    samples: list[tuple[int, tuple[float, float, float]]] = []
    for line in imu_path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        timestamp = _finite_number(payload.get("timestamp_ms"))
        acceleration = tuple(_finite_number(payload.get(axis)) for axis in ("ax", "ay", "az"))
        if timestamp is None or not timestamp.is_integer() or any(value is None for value in acceleration):
            continue
        samples.append((int(timestamp), tuple(float(value) for value in acceleration)))
    return sorted(samples, key=lambda sample: sample[0])


def _frame_files(frame_dir: Path) -> list[Path]:
    if not frame_dir.is_dir():
        raise ValueError(f"frame directory does not exist: {frame_dir}")
    return sorted(
        path for path in frame_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
    )


def _nearest_sample(
    samples: list[tuple[int, tuple[float, float, float]]], timestamps: list[int], target: int
) -> tuple[int, tuple[float, float, float]] | None:
    if not samples:
        return None
    index = bisect.bisect_left(timestamps, target)
    candidates = []
    if index > 0:
        candidates.append(samples[index - 1])
    if index < len(samples):
        candidates.append(samples[index])
    # Prefer the later sample when a frame is exactly between two IMU samples.
    return min(candidates, key=lambda sample: (abs(sample[0] - target), -sample[0]))


def build_imu_manifest(
    imu_path: Path | None,
    frame_dir: Path,
    fps: float,
    start_timestamp_ms: int,
    output_path: Path,
    acceleration_type: str = "gravity",
) -> dict[str, int]:
    """Write a FastGS v1 manifest and return matching statistics.

    The current glasses stream supplies accelerometer samples in JSONL. Since the
    video stream has no per-frame timestamps, frame timestamps are reconstructed
    from the session start and extraction FPS. Missing IMU data is represented by
    an empty manifest so the FastGS alignment stage can explicitly fall back.
    """
    if fps <= 0 or not math.isfinite(fps):
        raise ValueError("fps must be a positive finite number")
    if acceleration_type not in {"gravity", "specific_force"}:
        raise ValueError("unsupported acceleration_type")

    frames = _frame_files(frame_dir)
    samples = _load_acceleration_samples(imu_path)
    timestamps = [sample[0] for sample in samples]
    entries = []
    for index, frame in enumerate(frames):
        timestamp = int(round(start_timestamp_ms + index * 1000.0 / fps))
        sample = _nearest_sample(samples, timestamps, timestamp)
        if sample is None:
            continue
        _, acceleration = sample
        entries.append({
            "image": frame.name,
            "timestamp_ms": timestamp,
            "acceleration": list(acceleration),
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "version": 1,
                "acceleration_frame": "camera",
                "acceleration_type": acceleration_type,
                "frames": entries,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return {
        "frame_count": len(frames),
        "matched_count": len(entries),
        "valid_sample_count": len(samples),
    }
