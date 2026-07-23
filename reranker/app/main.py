from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app.model import QwenReranker
from app.settings import Settings, get_settings


class Scorer(Protocol):
    def score(self, query: str, documents: list[str]) -> list[float]: ...


class Candidate(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    document: str = Field(min_length=1, max_length=12000)


class RerankRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    candidates: list[Candidate] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_candidate_ids(self):
        ids = [candidate.id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate ids must be unique")
        return self


class RerankResult(BaseModel):
    id: str
    score: float


class RerankResponse(BaseModel):
    model: str
    results: list[RerankResult]


def create_app(settings: Settings | None = None, scorer: Scorer | None = None) -> FastAPI:
    service_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if scorer is None:
            loaded_scorer = QwenReranker(service_settings)
            await asyncio.to_thread(loaded_scorer.load)
            app.state.scorer = loaded_scorer
        yield

    app = FastAPI(title="Echo Qwen3 Reranker", version="1.0.0", lifespan=lifespan)
    app.state.settings = service_settings
    app.state.scorer = scorer
    app.state.inference_lock = asyncio.Lock()

    @app.get("/health")
    async def health(request: Request):
        return {
            "status": "ok" if request.app.state.scorer is not None else "loading",
            "model": service_settings.model_name,
            "quantization": "nf4",
            "max_batch_size": service_settings.max_batch_size,
        }

    @app.post("/rerank", response_model=RerankResponse)
    async def rerank(
        payload: RerankRequest,
        request: Request,
        x_internal_token: str | None = Header(default=None),
    ):
        if x_internal_token != service_settings.internal_token:
            raise HTTPException(status_code=401, detail="Invalid internal token")
        if len(payload.candidates) > service_settings.max_batch_size:
            raise HTTPException(status_code=422, detail="Too many candidates")
        active_scorer: Scorer | None = request.app.state.scorer
        if active_scorer is None:
            raise HTTPException(status_code=503, detail="Reranker model is not ready")

        documents = [candidate.document for candidate in payload.candidates]
        async with request.app.state.inference_lock:
            scores = await asyncio.to_thread(active_scorer.score, payload.query, documents)
        if len(scores) != len(payload.candidates):
            raise HTTPException(status_code=500, detail="Invalid score count from model")

        results = [
            RerankResult(id=candidate.id, score=max(0.0, min(1.0, score)))
            for candidate, score in zip(payload.candidates, scores, strict=True)
        ]
        results.sort(key=lambda item: item.score, reverse=True)
        return RerankResponse(model=service_settings.model_name, results=results)

    return app


app = create_app()
