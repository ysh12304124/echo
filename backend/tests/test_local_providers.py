"""本地 provider 集成测试。

默认跳过，除非设置 ECHO_RUN_LOCAL_TESTS=1 且本地模型服务可达。
用于在真实环境验证 OpenAI 兼容接口对接。
"""

import os

import httpx
import pytest

from app.providers import Settings

RUN = os.getenv("ECHO_RUN_LOCAL_TESTS") == "1"

pytestmark = pytest.mark.skipif(
    not RUN, reason="需要本地模型服务，设置 ECHO_RUN_LOCAL_TESTS=1 启用"
)


def _reachable(url: str) -> bool:
    try:
        httpx.get(url, timeout=2.0)
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_local_embedding_roundtrip():
    settings = Settings(provider_mode="local")
    if not _reachable(settings.embedding_base_url.rsplit("/v1", 1)[0]):
        pytest.skip("embedding 服务不可达")
    from app.providers.local.openai_client import OpenAICompatClient
    from app.providers.local.providers import LocalEmbeddingProvider

    provider = LocalEmbeddingProvider(
        OpenAICompatClient(settings.embedding_base_url, settings.embedding_api_key),
        settings.embedding_model,
    )
    result = await provider.embed("测试文本")
    assert isinstance(result.vector, list) and len(result.vector) > 0


@pytest.mark.asyncio
async def test_local_llm_structured_answer():
    settings = Settings(provider_mode="local")
    if not _reachable(settings.llm_base_url.rsplit("/v1", 1)[0]):
        pytest.skip("LLM 服务不可达")
    from app.providers.local.openai_client import OpenAICompatClient
    from app.providers.local.providers import LocalLLMProvider

    provider = LocalLLMProvider(
        OpenAICompatClient(settings.llm_base_url, settings.llm_api_key),
        settings.llm_model,
    )
    result = await provider.answer_query_structured(
        "会议在哪天？", "[transcript] 我们下周五开会 (confidence=high)"
    )
    assert "answer" in result and "confidence" in result
