from pathlib import Path

from httpx import ASGITransport, AsyncClient
import pytest

from app.main import app
from app.settings import get_settings


@pytest.mark.asyncio
async def test_transcribe_returns_weighted_confidence(monkeypatch, tmp_path: Path):
    audio = tmp_path / "query.pcm"
    audio.write_bytes(b"\x00\x00" * 16000)
    monkeypatch.setenv("COMPUTE_SHARED_BLOB_ROOT", str(tmp_path))
    monkeypatch.setenv("COMPUTE_INTERNAL_TOKEN", "test-token")
    get_settings.cache_clear()

    async def fake_whisper(*args, **kwargs):
        return {
            "segments": [
                {"text": "张经理", "start": 0.0, "end": 0.25, "avg_logprob": -0.2},
                {"text": "下周三交付", "start": 0.25, "end": 1.0, "avg_logprob": -0.6},
            ]
        }

    monkeypatch.setattr("app.analyze.audio.whisper_transcribe", fake_whisper)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/transcribe",
            headers={"X-Internal-Token": "test-token"},
            json={"audio_path": str(audio)},
        )

    assert response.status_code == 200
    assert response.json()["text"] == "张经理 下周三交付"
    assert response.json()["duration_ms"] == 1000
    assert response.json()["avg_logprob"] == pytest.approx(-0.5)


@pytest.mark.asyncio
async def test_transcribe_rejects_path_outside_shared_root(monkeypatch, tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    audio = tmp_path / "outside.pcm"
    audio.write_bytes(b"\x00\x00")
    monkeypatch.setenv("COMPUTE_SHARED_BLOB_ROOT", str(root))
    monkeypatch.setenv("COMPUTE_INTERNAL_TOKEN", "test-token")
    get_settings.cache_clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/transcribe",
            headers={"X-Internal-Token": "test-token"},
            json={"audio_path": str(audio)},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_transcribe_requires_internal_token(monkeypatch, tmp_path: Path):
    audio = tmp_path / "query.pcm"
    audio.write_bytes(b"\x00\x00")
    monkeypatch.setenv("COMPUTE_SHARED_BLOB_ROOT", str(tmp_path))
    monkeypatch.setenv("COMPUTE_INTERNAL_TOKEN", "test-token")
    get_settings.cache_clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/transcribe", json={"audio_path": str(audio)})
    assert response.status_code == 401
