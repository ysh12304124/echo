from app.domain.models import ImuSample
from app.services.spatial import detect_loop


def sample(timestamp_ms: int, gz: float = 0.0) -> ImuSample:
    return ImuSample(
        ax=0.0,
        ay=0.0,
        az=9.81,
        gx=0.0,
        gy=0.0,
        gz=gz,
        timestamp_ms=timestamp_ms,
    )


def test_detect_loop_integrates_gyro_rate_over_time():
    samples = [sample(i * 100, 3.141592653589793) for i in range(101)]

    result = detect_loop(samples)

    assert result.angle_degrees == 1800.0
    assert result.loop_complete is True
    assert result.confidence == 1.0


def test_detect_loop_ignores_invalid_intervals():
    result = detect_loop([sample(100, 1.0), sample(100, 1.0), sample(2200, 1.0)])

    assert result.angle_degrees == 0.0
    assert result.loop_complete is False
    assert result.confidence == 0.0
