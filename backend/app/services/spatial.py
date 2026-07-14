from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import ImuSample


LOOP_COMPLETION_DEGREES = 330.0


@dataclass(frozen=True)
class LoopDetection:
    loop_complete: bool
    angle_degrees: float
    confidence: float


def detect_loop(samples: list[ImuSample]) -> LoopDetection:
    """Estimate accumulated angular travel from gyro samples.

    This MVP reports angular travel only. Visual/COLMAP fusion is still needed
    for drift-corrected pose and production-grade loop closure detection.
    """
    if len(samples) < 2:
        return LoopDetection(False, 0.0, 0.0)

    angle_rad = 0.0
    valid_intervals = 0
    for previous, current in zip(samples, samples[1:]):
        dt = (current.timestamp_ms - previous.timestamp_ms) / 1000.0
        if dt <= 0 or dt > 1.0:
            continue
        rate = (current.gx ** 2 + current.gy ** 2 + current.gz ** 2) ** 0.5
        angle_rad += rate * dt
        valid_intervals += 1

    angle_degrees = angle_rad * 180.0 / 3.141592653589793
    data_confidence = min(1.0, valid_intervals / 25.0)
    completion_confidence = min(1.0, angle_degrees / 360.0)
    confidence = round(data_confidence * completion_confidence, 3)
    return LoopDetection(
        loop_complete=angle_degrees >= LOOP_COMPLETION_DEGREES,
        angle_degrees=round(angle_degrees, 2),
        confidence=confidence,
    )
