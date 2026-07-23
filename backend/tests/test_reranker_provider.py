import json

import httpx
import pytest

from app.providers.base import RerankCandidate, RerankerUnavailable
from app.providers.local.reranker import HttpRerankerProvider


@pytest.mark.asyncio
async def test_http_reranker_sends_all_candidates_in_one_request():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "Qwen3-Reranker-0.6B",
                "results": [
                    {"id": "b", "score": 0.9},
                    {"id": "a", "score": 0.2},
                ],
            },
        )

    provider = HttpRerankerProvider(
        "http://reranker",
        "Qwen3-Reranker-0.6B",
        "token",
        transport=httpx.MockTransport(handler),
    )
    results = await provider.rerank(
        "query",
        [RerankCandidate("a", "doc a"), RerankCandidate("b", "doc b")],
    )

    assert len(requests) == 1
    assert requests[0].headers["X-Internal-Token"] == "token"
    assert len(json.loads(requests[0].content)["candidates"]) == 2
    assert [(item.id, item.score) for item in results] == [("b", 0.9), ("a", 0.2)]


@pytest.mark.asyncio
async def test_http_reranker_rejects_missing_candidate_result():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"id": "a", "score": 0.8}]})

    provider = HttpRerankerProvider(
        "http://reranker", "model", "token", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RerankerUnavailable):
        await provider.rerank(
            "query", [RerankCandidate("a", "doc a"), RerankCandidate("b", "doc b")]
        )
