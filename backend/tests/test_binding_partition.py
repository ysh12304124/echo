import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.repositories.database import init_db


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_db()
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_partition_enforcement_rejects_illegal_combo(client: AsyncClient):
    # meeting 场景不允许归入 quality_time 分区
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time",
        "scene": "meeting",
        "partition": "quality_time",
        "title": "非法组合",
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_quality_time_forces_partition(client: AsyncClient):
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time",
        "scene": "quality_time",
        "partition": "work",  # 即便传 work 也应被强制为 quality_time
        "title": "亲子时光",
    })
    assert resp.status_code == 201
    assert resp.json()["partition"] == "quality_time"


@pytest.mark.asyncio
async def test_candidate_binding_created_for_parallel_capture(client: AsyncClient):
    # 先开时间会话
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time", "scene": "onsite", "partition": "work", "title": "并行现场",
    })
    time_session = resp.json()["session_id"]
    await client.post(
        f"/api/v1/ingest/sessions/{time_session}/audio",
        files={"file": ("a.pcm", io.BytesIO(b"audio"), "audio/pcm")},
        data={"timestamp_ms": 0},
    )

    # 并行进行空间采集并完成（captured_at 落在时间窗内）
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "space", "partition": "work", "title": "现场空间",
    })
    space_session = resp.json()["session_id"]
    for i in range(12):
        await client.post(
            f"/api/v1/ingest/sessions/{space_session}/frames",
            files={"file": (f"f{i}.jpg", io.BytesIO(f"f{i}".encode()), "image/jpeg")},
            data={"timestamp_ms": i * 1000},
        )
    space_id = (await client.post(f"/api/v1/ingest/sessions/{space_session}/complete")).json()["memory_id"]

    # 完成时间记忆 → 触发候选时空绑定
    time_memory_id = (await client.post(f"/api/v1/ingest/sessions/{time_session}/complete")).json()["memory_id"]

    resp = await client.get(f"/api/v1/memories/{time_memory_id}/bindings")
    assert resp.status_code == 200
    bindings = resp.json()["items"]
    assert any(b["space_memory_id"] == space_id and b["binding_type"] == "candidate" for b in bindings)

    # 确认绑定
    binding_id = bindings[0]["binding_id"]
    confirm = await client.post(f"/api/v1/bindings/{binding_id}/confirm")
    assert confirm.status_code == 200
    assert confirm.json()["user_confirmed"] is True


@pytest.mark.asyncio
async def test_quality_time_isolated_from_global_work(client: AsyncClient):
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time", "scene": "quality_time", "title": "私人时光",
    })
    session_id = resp.json()["session_id"]
    await client.post(
        f"/api/v1/ingest/sessions/{session_id}/audio",
        files={"file": ("a.pcm", io.BytesIO(b"audio"), "audio/pcm")},
        data={"timestamp_ms": 0},
    )
    qt_id = (await client.post(f"/api/v1/ingest/sessions/{session_id}/complete")).json()["memory_id"]

    # quality_time 记忆不应出现在 work 分区列表
    resp = await client.get("/api/v1/memories", params={"partition": "work"})
    work_ids = [i["memory_id"] for i in resp.json()["items"]]
    assert qt_id not in work_ids
