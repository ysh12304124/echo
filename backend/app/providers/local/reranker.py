from __future__ import annotations

import httpx

from app.providers.base import RerankCandidate, RerankResult, RerankerProvider, RerankerUnavailable


class HttpRerankerProvider(RerankerProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport

    async def rerank(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[RerankResult]:
        payload = {
            "query": query,
            "candidates": [
                {"id": candidate.id, "document": candidate.document}
                for candidate in candidates
            ],
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport
            ) as client:
                response = await client.post(
                    f"{self.base_url}/rerank",
                    headers={"X-Internal-Token": self.api_key},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RerankerUnavailable(f"reranker request failed: {exc}") from exc

        try:
            results = [
                RerankResult(id=item["id"], score=float(item["score"]))
                for item in data["results"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise RerankerUnavailable("reranker returned an invalid response") from exc
        expected_ids = {candidate.id for candidate in candidates}
        if {result.id for result in results} != expected_ids:
            raise RerankerUnavailable("reranker response does not match candidates")
        return results
