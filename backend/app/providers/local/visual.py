from __future__ import annotations

import math

import httpx

from app.providers.base import (
    EmbeddingResult,
    VisualEmbeddingProvider,
    VisualEmbeddingUnavailable,
)


class HttpVisualEmbeddingProvider(VisualEmbeddingProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        dimension: int,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.dimension = dimension
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Token": self.api_key}

    def _results(self, data: dict, texts: list[str]) -> list[EmbeddingResult]:
        vectors = data.get("vectors")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise VisualEmbeddingUnavailable("invalid visual embedding response")
        results = []
        for text, vector in zip(texts, vectors, strict=True):
            if (
                not isinstance(vector, list)
                or len(vector) != self.dimension
                or not all(math.isfinite(float(value)) for value in vector)
            ):
                raise VisualEmbeddingUnavailable("invalid visual embedding vector")
            results.append(EmbeddingResult(vector=[float(x) for x in vector], text=text))
        return results

    async def embed_text(self, text: str) -> EmbeddingResult:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/embed/text",
                    headers=self._headers(),
                    json={"texts": [text]},
                )
                response.raise_for_status()
                return self._results(response.json(), [text])[0]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise VisualEmbeddingUnavailable(
                f"visual text embedding request failed: {exc}"
            ) from exc

    async def embed_images(self, images: list[bytes]) -> list[EmbeddingResult]:
        files = [
            ("files", (f"frame-{index}.jpg", image, "image/jpeg"))
            for index, image in enumerate(images)
        ]
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/embed/images",
                    headers=self._headers(),
                    files=files,
                )
                response.raise_for_status()
                return self._results(response.json(), [""] * len(images))
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise VisualEmbeddingUnavailable(
                f"visual image embedding request failed: {exc}"
            ) from exc
