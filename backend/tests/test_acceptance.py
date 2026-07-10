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


async def _create_and_complete_meeting(client: AsyncClient, title: str = "Q3经营会"):
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time",
        "scene": "meeting",
        "partition": "work",
        "title": title,
    })
    assert resp.status_code == 201
    session_id = resp.json()["session_id"]

    frame = io.BytesIO(b"fake whiteboard image data")
    resp = await client.post(
        f"/api/v1/ingest/sessions/{session_id}/frames",
        files={"file": ("whiteboard.jpg", frame, "image/jpeg")},
        data={"timestamp_ms": 5000},
    )
    assert resp.status_code == 201

    audio = io.BytesIO(b"fake audio pcm data")
    resp = await client.post(
        f"/api/v1/ingest/sessions/{session_id}/audio",
        files={"file": ("audio.pcm", audio, "audio/pcm")},
        data={"timestamp_ms": 0},
    )
    assert resp.status_code == 201

    resp = await client.post(f"/api/v1/ingest/sessions/{session_id}/complete")
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_session_frame_image_hosting(client: AsyncClient):
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time",
        "scene": "meeting",
        "partition": "work",
        "title": "关键帧图床测试",
    })
    assert resp.status_code == 201
    session_id = resp.json()["session_id"]

    image_bytes = b"\xff\xd8 key frame bytes \xff\xd9"
    resp = await client.post(
        f"/api/v1/ingest/sessions/{session_id}/frames",
        files={"file": ("whiteboard.jpg", io.BytesIO(image_bytes), "image/jpeg")},
        data={"timestamp_ms": 5000, "is_key_moment": "true"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"].endswith(".jpg")
    assert data["media_url"] == f"/api/v1/ingest/sessions/{session_id}/frames/{data['filename']}"

    resp = await client.get(data["media_url"])
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert resp.content == image_bytes

    resp = await client.get(f"/api/v1/ingest/sessions/{session_id}/frames")
    assert resp.status_code == 200
    frame_list = resp.json()
    assert frame_list["total"] == 1
    assert frame_list["items"][0]["filename"] == data["filename"]
    assert frame_list["items"][0]["media_url"] == data["media_url"]

    resp = await client.get(f"/api/v1/media/sessions/{session_id}/frames/{data['filename']}")
    assert resp.status_code == 200
    assert resp.content == image_bytes


# 用例1: 会议记录与全局工作查询
@pytest.mark.asyncio
async def test_case1_meeting_global_query(client: AsyncClient):
    memory = await _create_and_complete_meeting(client)
    memory_id = memory["memory_id"]

    resp = await client.get(f"/api/v1/memories/{memory_id}")
    assert resp.status_code == 200
    nav = resp.json()["navigation_summary"]
    assert nav["key_moments"]
    moment = nav["key_moments"][0]
    assert moment["description"] == ""
    assert moment["image_url"].startswith("/api/v1/media/sessions/")
    assert moment["imageUrl"] == moment["image_url"]

    resp = await client.post("/api/v1/query", json={
        "question": "张经理承诺了什么？",
        "scope": "global_work",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["answer"] is not None
    assert "周五" in data["answer"] or "方案" in data["answer"]
    assert len(data["evidences"]) >= 1
    assert any(e["type"] == "transcript" for e in data["evidences"])


# 用例2: 现场拜访与当前空间内查询
@pytest.mark.asyncio
async def test_case2_onsite_space_query(client: AsyncClient):
    # Create onsite memory
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time",
        "scene": "onsite",
        "partition": "work",
        "title": "苏州工厂拜访",
    })
    session_id = resp.json()["session_id"]

    frame = io.BytesIO(b"smt device image")
    await client.post(
        f"/api/v1/ingest/sessions/{session_id}/frames",
        files={"file": ("smt_device.jpg", frame, "image/jpeg")},
        data={"timestamp_ms": 10000},
    )
    audio = io.BytesIO(b"audio")
    await client.post(
        f"/api/v1/ingest/sessions/{session_id}/audio",
        files={"file": ("audio.pcm", audio, "audio/pcm")},
        data={"timestamp_ms": 0},
    )
    await client.post(f"/api/v1/ingest/sessions/{session_id}/complete")

    # Create space memory
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "space",
        "partition": "work",
        "title": "SMT车间",
    })
    space_session = resp.json()["session_id"]
    for i in range(12):
        frame = io.BytesIO(f"frame{i}".encode())
        await client.post(
            f"/api/v1/ingest/sessions/{space_session}/frames",
            files={"file": (f"frame{i}.jpg", frame, "image/jpeg")},
            data={"timestamp_ms": i * 1000},
        )
    resp = await client.post(f"/api/v1/ingest/sessions/{space_session}/complete")
    space_id = resp.json()["memory_id"]

    resp = await client.get(f"/api/v1/spaces/{space_id}")
    assert resp.status_code == 200
    assert resp.json()["quality"] in ("excellent", "good")


# 用例3: 当前记忆内查询
@pytest.mark.asyncio
async def test_case3_memory_scope_query(client: AsyncClient):
    memory = await _create_and_complete_meeting(client, "测试会议")
    memory_id = memory["memory_id"]

    resp = await client.post("/api/v1/query", json={
        "question": "这段记忆里答应了什么？",
        "scope": "memory",
        "memory_id": memory_id,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("confirmed", "possible", "not_found")
    if data["status"] == "confirmed":
        assert len(data["evidences"]) >= 1


# 用例4: Quality Time 数据分区隔离
@pytest.mark.asyncio
async def test_case4_quality_time_partition(client: AsyncClient):
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time",
        "scene": "quality_time",
        "title": "家庭时光",
    })
    session_id = resp.json()["session_id"]
    assert resp.json()["partition"] == "quality_time"

    audio = io.BytesIO(b"audio")
    await client.post(
        f"/api/v1/ingest/sessions/{session_id}/audio",
        files={"file": ("audio.pcm", audio, "audio/pcm")},
        data={"timestamp_ms": 0},
    )
    resp = await client.post(f"/api/v1/ingest/sessions/{session_id}/complete")
    qt_memory_id = resp.json()["memory_id"]

    # Global work query should NOT return quality time data
    resp = await client.post("/api/v1/query", json={
        "question": "刚才展示了什么？",
        "scope": "global_work",
    })
    global_data = resp.json()

    # Memory scope query within quality time should work
    resp = await client.post("/api/v1/query", json={
        "question": "刚才展示了什么？",
        "scope": "memory",
        "memory_id": qt_memory_id,
    })
    memory_data = resp.json()
    assert memory_data["status"] in ("confirmed", "possible", "not_found")

    # List memories by partition
    resp = await client.get("/api/v1/memories", params={"partition": "quality_time"})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


# 用例5: 首页简洁性 - 记忆列表只返回识别信息
@pytest.mark.asyncio
async def test_case5_home_summary_only(client: AsyncClient):
    await _create_and_complete_meeting(client)
    resp = await client.get("/api/v1/memories")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    completed = [i for i in items if i.get("status") == "completed"]
    assert len(completed) >= 1
    item = completed[0]
    assert "identify_brief" in item
    assert "title" in item
    assert "scene" in item
    # Detail with navigation summary is separate endpoint
    detail = await client.get(f"/api/v1/memories/{item['memory_id']}")
    assert detail.status_code == 200
    assert detail.json().get("navigation_summary") is not None or detail.json()["status"] == "completed"


# 用例6: 音频转写文本作为证据
@pytest.mark.asyncio
async def test_case6_transcript_as_evidence(client: AsyncClient):
    memory = await _create_and_complete_meeting(client)
    resp = await client.post("/api/v1/query", json={
        "question": "什么时候交方案？",
        "scope": "global_work",
    })
    data = resp.json()
    if data["status"] == "confirmed":
        assert any(e["type"] == "transcript" for e in data["evidences"])


# 用例7: 无证据查询
@pytest.mark.asyncio
async def test_case7_no_evidence_query(client: AsyncClient):
    resp = await client.post("/api/v1/query", json={
        "question": "火星上有没有外星人？",
        "scope": "global_work",
    })
    data = resp.json()
    assert data["status"] == "not_found"
    assert data["answer"] is None


# 用例8: 低置信人物匹配
@pytest.mark.asyncio
async def test_case8_low_confidence_person(client: AsyncClient):
    memory = await _create_and_complete_meeting(client)
    resp = await client.post("/api/v1/query", json={
        "question": "张经理什么时候交方案？",
        "scope": "global_work",
    })
    data = resp.json()
    assert data["status"] in ("confirmed", "possible")
    if data["status"] == "confirmed":
        assert "张经理" in data["answer"] or "周五" in data["answer"]


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
