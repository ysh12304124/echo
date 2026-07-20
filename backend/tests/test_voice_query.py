from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
import pytest

from app.api import routes
from app.main import app
from app.providers.base import VectorIndexMismatch
from app.providers.mock.providers import LocalBlobStore
from app.schemas import QueryResponse


class FakeCompute:
    def __init__(self, payload):
        self.payload = payload
        self.paths: list[str] = []

    async def transcribe(self, audio_path: str):
        self.paths.append(audio_path)
        assert Path(audio_path).is_file()
        return self.payload


class FakeEngine:
    calls: list[tuple[str, object]] = []

    def __init__(self, _repo):
        pass

    async def query(self, question, scope, memory_id=None, space_id=None):
        self.calls.append((question, scope))
        return QueryResponse(query_id=uuid4(), status="not_found")


class MismatchedIndexEngine(FakeEngine):
    async def query(self, question, scope, memory_id=None, space_id=None):
        raise VectorIndexMismatch("index uses nomic")


@pytest.mark.asyncio
async def test_voice_query_transcribes_queries_and_cleans_temp_audio(monkeypatch, tmp_path):
    compute = FakeCompute({"text": "张经理什么时候交付样品", "avg_logprob": -0.3})
    monkeypatch.setattr(routes, "get_compute_client", lambda: compute)
    monkeypatch.setattr(routes, "QueryEngine", FakeEngine)
    monkeypatch.setattr(
        routes,
        "get_provider_factory",
        lambda: SimpleNamespace(blob_store=lambda: LocalBlobStore(str(tmp_path))),
    )
    FakeEngine.calls.clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/query/voice",
            files={"file": ("query.pcm", b"\x00\x00" * 16000, "audio/pcm")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["asr_accepted"] is True
    assert body["transcript"] == "张经理什么时候交付样品"
    assert FakeEngine.calls[0][1].value == "global_work"
    assert not list(tmp_path.rglob("*.pcm"))


@pytest.mark.asyncio
async def test_voice_query_filters_low_confidence_without_search(monkeypatch, tmp_path):
    compute = FakeCompute({"text": "听不清", "avg_logprob": -1.4})
    monkeypatch.setattr(routes, "get_compute_client", lambda: compute)
    monkeypatch.setattr(routes, "QueryEngine", FakeEngine)
    monkeypatch.setattr(
        routes,
        "get_provider_factory",
        lambda: SimpleNamespace(blob_store=lambda: LocalBlobStore(str(tmp_path))),
    )
    FakeEngine.calls.clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/query/voice",
            files={"file": ("query.pcm", b"\x00\x00", "audio/pcm")},
        )

    assert response.status_code == 200
    assert response.json()["asr_accepted"] is False
    assert response.json()["result"] is None
    assert FakeEngine.calls == []


@pytest.mark.asyncio
async def test_voice_query_rejects_audio_over_sixty_seconds(monkeypatch):
    called = False

    async def fail_transcribe(_path):
        nonlocal called
        called = True
        raise AssertionError("ASR should not be called")

    monkeypatch.setattr(routes, "get_compute_client", lambda: SimpleNamespace(transcribe=fail_transcribe))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/query/voice",
            files={"file": ("query.pcm", b"\x00\x00" * (16000 * 60 + 1), "audio/pcm")},
        )
    assert response.status_code == 400
    assert called is False


@pytest.mark.asyncio
async def test_voice_query_returns_503_when_embedding_index_requires_rebuild(
    monkeypatch, tmp_path
):
    compute = FakeCompute({"text": "张经理什么时候交付样品", "avg_logprob": -0.3})
    monkeypatch.setattr(routes, "get_compute_client", lambda: compute)
    monkeypatch.setattr(routes, "QueryEngine", MismatchedIndexEngine)
    monkeypatch.setattr(
        routes,
        "get_provider_factory",
        lambda: SimpleNamespace(blob_store=lambda: LocalBlobStore(str(tmp_path))),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/query/voice",
            files={"file": ("query.pcm", b"\x00\x00", "audio/pcm")},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Embedding index requires rebuild"
    assert not list(tmp_path.rglob("*.pcm"))
