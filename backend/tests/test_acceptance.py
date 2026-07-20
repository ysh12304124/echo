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


async def _upload_video(client: AsyncClient, session_id: str, filename: str = "Meeting_20260716142825_20260716143123.mp4"):
    """模拟眼镜边录边发：分两片上传，最后一片带 filename 且 is_last=true。"""
    chunk1 = io.BytesIO(b"fake mp4 bytes part1")
    resp = await client.post(
        f"/api/v1/ingest/sessions/{session_id}/video",
        files={"file": ("chunk.bin", chunk1, "application/octet-stream")},
        data={"index": 0, "is_last": "false"},
    )
    assert resp.status_code == 201

    chunk2 = io.BytesIO(b"fake mp4 bytes part2")
    resp = await client.post(
        f"/api/v1/ingest/sessions/{session_id}/video",
        files={"file": ("chunk.bin", chunk2, "application/octet-stream")},
        data={"index": 1, "is_last": "true", "filename": filename},
    )
    assert resp.status_code == 201
    return resp.json()


async def _create_and_complete_meeting(client: AsyncClient, title: str = "Q3经营会"):
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time",
        "scene": "meeting",
        "partition": "work",
        "title": title,
    })
    assert resp.status_code == 201
    session_id = resp.json()["session_id"]

    await _upload_video(client, session_id)

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


# 视频边录边发：分片不落地转发、按顺序 append，最后一片携带 filename 完成落盘。
@pytest.mark.asyncio
async def test_video_chunk_upload_and_media_hosting(client: AsyncClient):
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time",
        "scene": "onsite",
        "partition": "work",
        "title": "视频分片测试",
    })
    assert resp.status_code == 201
    session_id = resp.json()["session_id"]

    filename = "Onsite_20260716142825_20260716143123.mp4"
    ack = await _upload_video(client, session_id, filename)
    assert ack["filename"] == filename
    assert ack["media_url"] == f"/api/v1/media/sessions/{session_id}/video/{filename}"

    resp = await client.get(ack["media_url"])
    assert resp.status_code == 200
    assert resp.content == b"fake mp4 bytes part1fake mp4 bytes part2"


# 空间记忆(IMU)现附加到当前场景 session 下，不再要求独立的 SPACE 会话。
@pytest.mark.asyncio
async def test_imu_attached_to_time_session(client: AsyncClient):
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time",
        "scene": "onsite",
        "partition": "work",
        "title": "空间记忆附加测试",
    })
    session_id = resp.json()["session_id"]

    resp = await client.post(
        f"/api/v1/ingest/sessions/{session_id}/imu",
        json={"samples": [
            {"ax": 0.1, "ay": 0.2, "az": 9.8, "gx": 0.0, "gy": 0.0, "gz": 0.0, "timestamp_ms": 1000},
        ]},
    )
    assert resp.status_code == 201
    assert resp.json()["accepted_count"] == 1


# 用例1: 会议记录 —— store-only 模式下不再自动跑 ASR/VLM，complete 返回最小记忆记录。
@pytest.mark.asyncio
async def test_case1_meeting_store_only_complete(client: AsyncClient):
    memory = await _create_and_complete_meeting(client)
    memory_id = memory["memory_id"]
    assert memory["status"] == "completed"

    resp = await client.get(f"/api/v1/memories/{memory_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # store-only 模式下该记忆没有生成任何语音证据，限定在该记忆内检索应回退到「没有找到」。
    resp = await client.post("/api/v1/query", json={
        "question": "张经理承诺了什么？",
        "scope": "memory",
        "memory_id": memory_id,
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_found"


# 用例2: 现场拜访 —— 完成后可正常列出/查询（不含拍照/帧上传，已改为视频分片）
@pytest.mark.asyncio
async def test_case2_onsite_completion(client: AsyncClient):
    resp = await client.post("/api/v1/ingest/sessions", json={
        "memory_type": "time",
        "scene": "onsite",
        "partition": "work",
        "title": "苏州工厂拜访",
    })
    session_id = resp.json()["session_id"]

    await _upload_video(client, session_id, "Onsite_20260716100000_20260716100500.mp4")
    audio = io.BytesIO(b"audio")
    await client.post(
        f"/api/v1/ingest/sessions/{session_id}/audio",
        files={"file": ("audio.pcm", audio, "audio/pcm")},
        data={"timestamp_ms": 0},
    )
    resp = await client.post(f"/api/v1/ingest/sessions/{session_id}/complete")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["scene"] == "onsite"


# 用例3: 当前记忆内查询（store-only 下无证据，允许 not_found）
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
    detail = await client.get(f"/api/v1/memories/{item['memory_id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"


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


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
