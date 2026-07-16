import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.providers import get_settings
import app.providers as providers_module


@pytest.mark.asyncio
async def test_space_completion_returns_processing_then_publishes_mock_model(monkeypatch):
    monkeypatch.setenv("ECHO_PROVIDER_MODE", "mock")
    get_settings.cache_clear()
    providers_module._provider_factory = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/ingest/sessions",
            json={"memory_type": "space", "partition": "work", "title": "异步空间"},
        )
        assert response.status_code == 201
        session_id = response.json()["session_id"]

        # 眼镜端已不再拍照，帧上传接口已移除；空间重建 mock 流程不依赖帧内容即可完成。
        response = await client.post(f"/api/v1/ingest/sessions/{session_id}/complete")
        assert response.status_code == 200
        memory_id = response.json()["memory_id"]
        assert response.json()["status"] == "processing"

        for _ in range(20):
            await asyncio.sleep(0.02)
            space = await client.get(f"/api/v1/spaces/{memory_id}")
            if space.json()["status"] != "processing":
                break

        assert space.status_code == 200
        payload = space.json()
        assert payload["status"] == "completed"
        assert payload["model_format"] == "glb"
        assert payload["model_url"] == "/api/v1/media/placeholder_3d.glb"
