from httpx import ASGITransport, AsyncClient
import pytest

from app.main import create_app
from app.settings import Settings


class FakeScorer:
    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, documents: list[str]) -> list[float]:
        self.calls.append((query, documents))
        return [index / 20 for index in range(len(documents))]


@pytest.mark.asyncio
async def test_rerank_scores_candidates_in_one_batch_and_sorts_results():
    scorer = FakeScorer()
    settings = Settings(internal_token="test-token")
    app = create_app(settings, scorer)
    candidates = [
        {"id": str(index), "document": f"document {index}"} for index in range(20)
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/rerank",
            headers={"X-Internal-Token": "test-token"},
            json={"query": "query", "candidates": candidates},
        )

    assert response.status_code == 200
    assert len(scorer.calls) == 1
    assert len(scorer.calls[0][1]) == 20
    assert response.json()["results"][0]["id"] == "19"


@pytest.mark.asyncio
async def test_rerank_requires_internal_token():
    app = create_app(Settings(internal_token="test-token"), FakeScorer())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/rerank",
            json={"query": "query", "candidates": [{"id": "1", "document": "doc"}]},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rerank_rejects_more_than_twenty_candidates():
    app = create_app(Settings(internal_token="test-token"), FakeScorer())
    candidates = [
        {"id": str(index), "document": f"document {index}"} for index in range(21)
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/rerank",
            headers={"X-Internal-Token": "test-token"},
            json={"query": "query", "candidates": candidates},
        )
    assert response.status_code == 422
