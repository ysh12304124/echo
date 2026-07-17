import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.providers import get_settings
import app.providers as providers_module


@pytest.mark.asyncio
async def test_space_completion_submits_to_compute_and_completes(monkeypatch):
    """空间记忆 complete 应把重建任务异步甩给算力服务 (submit_space)。

    compute_provider_mode=mock 时 MockComputeClient 会在本地同步回填占位结果
    (效果等同于"秒级完成")，验证的是 complete_session -> submit_space -> 回调落库
    这条链路整体打通，而不是真实的重建质量(那部分由 compute/analyze/space 后续实现)。
    """
    monkeypatch.setenv("ECHO_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ECHO_COMPUTE_PROVIDER_MODE", "mock")
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

        response = await client.post(f"/api/v1/ingest/sessions/{session_id}/complete")
        assert response.status_code == 200
        memory_id = response.json()["memory_id"]
        assert response.json()["status"] == "completed"

        space = await client.get(f"/api/v1/spaces/{memory_id}")
        assert space.status_code == 200
        payload = space.json()
        assert payload["status"] == "completed"
        assert payload["identify_brief"] == "(mock 占位结果)"
