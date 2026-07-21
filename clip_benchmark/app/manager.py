from __future__ import annotations

import asyncio
import hashlib
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.encoder import ChineseClipEncoder, Quantization
from app.settings import Settings

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
QUANTIZATIONS: tuple[Quantization, ...] = ("fp16", "int8", "nf4")


class Encoder(Protocol):
    quantization: Quantization | None

    def load(self, quantization: Quantization) -> None: ...

    def unload(self) -> None: ...

    def encode_texts(self, texts: list[str]) -> list[list[float]]: ...

    def encode_images(self, images: list[bytes]) -> list[list[float]]: ...

    def memory_stats(self) -> dict: ...


@dataclass(frozen=True)
class CatalogImage:
    id: str
    path: Path
    relative_path: str


@dataclass(frozen=True)
class IndexedImage:
    image: CatalogImage
    vector: list[float]


class BenchmarkManager:
    def __init__(self, settings: Settings, encoder: Encoder | None = None):
        self.settings = settings
        self.encoder = encoder or ChineseClipEncoder(
            settings.model_path, settings.text_max_length
        )
        self.lock = asyncio.Lock()
        self.state = "not_loaded"
        self.error: str | None = None
        self.quantization: Quantization | None = None
        self.indexed: list[IndexedImage] = []
        self.model_load_ms: float | None = None
        self.index_build_ms: float | None = None

    def scan_images(self) -> list[CatalogImage]:
        root = self.settings.resolved_image_root
        if not root.is_dir():
            raise RuntimeError(f"Image root does not exist: {root}")
        images: list[CatalogImage] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            image_id = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]
            images.append(CatalogImage(image_id, path.resolve(), relative))
        if not images:
            raise RuntimeError(f"No images found under: {root}")
        return images

    async def reload(self, quantization: str) -> None:
        if quantization not in QUANTIZATIONS:
            raise ValueError(f"Unsupported quantization: {quantization}")
        selected: Quantization = quantization  # type: ignore[assignment]
        async with self.lock:
            self.state = "loading_model"
            self.error = None
            self.indexed = []
            try:
                await asyncio.to_thread(self.encoder.unload)
                started = time.perf_counter()
                await asyncio.to_thread(self.encoder.load, selected)
                self.model_load_ms = (time.perf_counter() - started) * 1000
                self.quantization = selected

                self.state = "indexing_images"
                started = time.perf_counter()
                catalog = await asyncio.to_thread(self.scan_images)
                indexed: list[IndexedImage] = []
                batch_size = self.settings.image_batch_size
                for offset in range(0, len(catalog), batch_size):
                    batch = catalog[offset : offset + batch_size]
                    payloads = await asyncio.to_thread(
                        lambda: [item.path.read_bytes() for item in batch]
                    )
                    vectors = await asyncio.to_thread(
                        self.encoder.encode_images, payloads
                    )
                    if len(vectors) != len(batch):
                        raise RuntimeError("Image embedding count mismatch")
                    indexed.extend(
                        IndexedImage(item, vector)
                        for item, vector in zip(batch, vectors, strict=True)
                    )
                self.indexed = indexed
                self.index_build_ms = (time.perf_counter() - started) * 1000
                self.state = "ready"
            except Exception as exc:
                self.state = "error"
                self.error = str(exc)
                raise

    async def search(self, query: str) -> dict:
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("Query must not be blank")
        async with self.lock:
            if self.state != "ready" or not self.indexed:
                raise RuntimeError("Model or image index is not ready")
            started = time.perf_counter()
            text_started = time.perf_counter()
            vectors = await asyncio.to_thread(
                self.encoder.encode_texts, [clean_query]
            )
            text_ms = (time.perf_counter() - text_started) * 1000
            if len(vectors) != 1:
                raise RuntimeError("Text embedding count mismatch")
            query_vector = vectors[0]

            rank_started = time.perf_counter()
            scored: list[tuple[IndexedImage, float]] = []
            for item in self.indexed:
                score = sum(a * b for a, b in zip(query_vector, item.vector, strict=True))
                if math.isfinite(score):
                    scored.append((item, score))
            scored.sort(key=lambda pair: pair[1], reverse=True)
            rank_ms = (time.perf_counter() - rank_started) * 1000
            top = scored[: min(self.settings.top_k, len(scored))]
            total_ms = (time.perf_counter() - started) * 1000
            return {
                "query": clean_query,
                "quantization": self.quantization,
                "total_candidates": len(scored),
                "returned": len(top),
                "timings_ms": {
                    "text_embedding": round(text_ms, 2),
                    "ranking": round(rank_ms, 2),
                    "total": round(total_ms, 2),
                },
                "results": [
                    {
                        "rank": rank,
                        "image_id": item.image.id,
                        "filename": item.image.path.name,
                        "relative_path": item.image.relative_path,
                        "similarity": round(score, 6),
                        "image_url": f"/api/images/{item.image.id}",
                    }
                    for rank, (item, score) in enumerate(top, start=1)
                ],
            }

    def find_image(self, image_id: str) -> Path | None:
        for item in self.indexed:
            if item.image.id == image_id:
                return item.image.path
        return None

    def status(self) -> dict:
        return {
            "state": self.state,
            "error": self.error,
            "quantization": self.quantization,
            "quantization_options": list(QUANTIZATIONS),
            "model_path": self.settings.model_path,
            "image_root": str(self.settings.resolved_image_root),
            "image_count": len(self.indexed),
            "embedding_dimension": len(self.indexed[0].vector) if self.indexed else 512,
            "model_load_ms": round(self.model_load_ms, 2) if self.model_load_ms else None,
            "index_build_ms": round(self.index_build_ms, 2) if self.index_build_ms else None,
            "gpu": self.encoder.memory_stats(),
        }
