from __future__ import annotations

import asyncio
import math
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from app.model import ChineseClipEncoder
from app.settings import Settings, get_settings


class Encoder(Protocol):
    def encode_texts(self, texts: list[str]) -> list[list[float]]: ...

    def encode_images(self, images: list[bytes]) -> list[list[float]]: ...


class TextEmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=16)


class EmbeddingResponse(BaseModel):
    model: str
    dimension: int
    vectors: list[list[float]]


def create_app(
    settings: Settings | None = None, encoder: Encoder | None = None
) -> FastAPI:
    service_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if encoder is None:
            loaded_encoder = ChineseClipEncoder(service_settings)
            await asyncio.to_thread(loaded_encoder.load)
            app.state.encoder = loaded_encoder
        yield

    app = FastAPI(
        title="Echo Chinese-CLIP Embedding",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = service_settings
    app.state.encoder = encoder
    app.state.inference_lock = asyncio.Lock()

    def authorize(token: str | None) -> None:
        if token != service_settings.internal_token:
            raise HTTPException(status_code=401, detail="Invalid internal token")

    def validate_vectors(vectors: list[list[float]], expected_count: int) -> None:
        if len(vectors) != expected_count:
            raise HTTPException(status_code=500, detail="Invalid embedding count")
        if any(
            len(vector) != service_settings.embedding_dimension
            or not all(math.isfinite(value) for value in vector)
            for vector in vectors
        ):
            raise HTTPException(status_code=500, detail="Invalid embedding vector")

    @app.get("/health")
    async def health(request: Request):
        return {
            "status": "ok" if request.app.state.encoder is not None else "loading",
            "model": service_settings.model_name,
            "source_precision": "fp16",
            "runtime_quantization": "nf4",
            "dimension": service_settings.embedding_dimension,
            "max_batch_size": service_settings.max_batch_size,
        }

    @app.post("/embed/text", response_model=EmbeddingResponse)
    async def embed_text(
        payload: TextEmbeddingRequest,
        request: Request,
        x_internal_token: str | None = Header(default=None),
    ):
        authorize(x_internal_token)
        texts = [text.strip() for text in payload.texts]
        if any(not text for text in texts):
            raise HTTPException(status_code=422, detail="Text must not be blank")
        active_encoder: Encoder | None = request.app.state.encoder
        if active_encoder is None:
            raise HTTPException(status_code=503, detail="Model is not ready")
        async with request.app.state.inference_lock:
            vectors = await asyncio.to_thread(active_encoder.encode_texts, texts)
        validate_vectors(vectors, len(texts))
        return EmbeddingResponse(
            model=service_settings.model_name,
            dimension=service_settings.embedding_dimension,
            vectors=vectors,
        )

    @app.post("/embed/images", response_model=EmbeddingResponse)
    async def embed_images(
        request: Request,
        files: list[UploadFile] = File(...),
        x_internal_token: str | None = Header(default=None),
    ):
        authorize(x_internal_token)
        if not files or len(files) > service_settings.max_batch_size:
            raise HTTPException(status_code=422, detail="Invalid image batch size")
        images: list[bytes] = []
        for upload in files:
            if upload.content_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise HTTPException(status_code=415, detail="Unsupported image type")
            data = await upload.read(service_settings.max_image_bytes + 1)
            if not data or len(data) > service_settings.max_image_bytes:
                raise HTTPException(status_code=413, detail="Invalid image size")
            images.append(data)
        active_encoder: Encoder | None = request.app.state.encoder
        if active_encoder is None:
            raise HTTPException(status_code=503, detail="Model is not ready")
        async with request.app.state.inference_lock:
            try:
                vectors = await asyncio.to_thread(
                    active_encoder.encode_images, images
                )
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="Invalid image") from exc
        validate_vectors(vectors, len(images))
        return EmbeddingResponse(
            model=service_settings.model_name,
            dimension=service_settings.embedding_dimension,
            vectors=vectors,
        )

    return app


app = create_app()
