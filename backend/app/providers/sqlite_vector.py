"""持久化向量检索：向量存 SQLite，加载入 numpy 做余弦相似度 + metadata 过滤。

MVP 规模下（单机、万级向量）足够；避免引入 FAISS 等重依赖。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

import aiosqlite
import numpy as np

from app.providers.base import VectorIndexInfo, VectorIndexMismatch, VectorStore


class SqliteVectorStore(VectorStore):
    def __init__(
        self,
        db_path: str = "./data/vectors.db",
        embedding_model: str | None = None,
        embedding_dimension: int | None = None,
    ):
        self.db_path = db_path
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def _ensure_init(self) -> None:
        if self._initialized:
            return
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS vectors (
                    id TEXT PRIMARY KEY,
                    vector TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS vector_index_metadata (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    embedding_model TEXT NOT NULL,
                    dimension INTEGER NOT NULL
                )
                """
            )
            await db.commit()
        self._initialized = True

    def _validate_vector(
        self, vector: list[float], expected_dimension: int | None = None
    ) -> int:
        dimension = len(vector)
        if dimension == 0 or not all(math.isfinite(value) for value in vector):
            raise ValueError("vector must contain finite values")
        configured_dimension = expected_dimension or self.embedding_dimension
        if configured_dimension and dimension != configured_dimension:
            raise VectorIndexMismatch(
                f"embedding dimension mismatch: expected {configured_dimension}, "
                f"got {dimension}"
            )
        return dimension

    async def _read_index_metadata(
        self, db: aiosqlite.Connection
    ) -> tuple[str, int] | None:
        async with db.execute(
            "SELECT embedding_model, dimension FROM vector_index_metadata WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
        return (str(row[0]), int(row[1])) if row else None

    async def _count(self, db: aiosqlite.Connection) -> int:
        async with db.execute("SELECT COUNT(*) FROM vectors") as cursor:
            row = await cursor.fetchone()
        return int(row[0])

    def _assert_index_compatible(
        self, metadata: tuple[str, int], vector_dimension: int | None = None
    ) -> None:
        model, dimension = metadata
        if self.embedding_model and model != self.embedding_model:
            raise VectorIndexMismatch(
                f"embedding model mismatch: index={model}, configured={self.embedding_model}"
            )
        if self.embedding_dimension and dimension != self.embedding_dimension:
            raise VectorIndexMismatch(
                f"embedding dimension mismatch: index={dimension}, "
                f"configured={self.embedding_dimension}"
            )
        if vector_dimension and dimension != vector_dimension:
            raise VectorIndexMismatch(
                f"query dimension mismatch: index={dimension}, query={vector_dimension}"
            )

    @staticmethod
    def _metadata_with_index(metadata: dict, model: str, dimension: int) -> dict:
        return {
            **metadata,
            "embedding_model": model,
            "embedding_dimension": dimension,
        }

    async def upsert(self, id: str, vector: list[float], metadata: dict) -> None:
        await self._ensure_init()
        vector_dimension = self._validate_vector(vector)
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute("BEGIN IMMEDIATE")
                index_metadata = await self._read_index_metadata(db)
                count = await self._count(db)
                if index_metadata is None:
                    if count:
                        raise VectorIndexMismatch(
                            "vector index metadata is missing; rebuild the index"
                        )
                    index_metadata = (
                        self.embedding_model or "unspecified",
                        self.embedding_dimension or vector_dimension,
                    )
                    await db.execute(
                        "INSERT INTO vector_index_metadata "
                        "(id, embedding_model, dimension) VALUES (1, ?, ?)",
                        index_metadata,
                    )
                self._assert_index_compatible(index_metadata, vector_dimension)
                model, dimension = index_metadata
                await db.execute(
                    "INSERT OR REPLACE INTO vectors (id, vector, metadata) VALUES (?, ?, ?)",
                    (
                        id,
                        json.dumps(vector),
                        json.dumps(
                            self._metadata_with_index(metadata, model, dimension)
                        ),
                    ),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def search(
        self, vector: list[float], top_k: int = 10, filter: Optional[dict] = None
    ) -> list[tuple[str, float, dict]]:
        await self._ensure_init()
        vector_dimension = self._validate_vector(vector)
        q = np.array(vector, dtype=np.float32)
        q_norm = np.linalg.norm(q) + 1e-8
        results: list[tuple[str, float, dict]] = []
        async with aiosqlite.connect(self.db_path) as db:
            index_metadata = await self._read_index_metadata(db)
            count = await self._count(db)
            if index_metadata is None:
                if count:
                    raise VectorIndexMismatch(
                        "vector index metadata is missing; rebuild the index"
                    )
                return []
            self._assert_index_compatible(index_metadata, vector_dimension)
            model, dimension = index_metadata
            async with db.execute("SELECT id, vector, metadata FROM vectors") as cursor:
                async for row in cursor:
                    vid, vec_json, meta_json = row
                    meta = json.loads(meta_json)
                    if (
                        meta.get("embedding_model") != model
                        or meta.get("embedding_dimension") != dimension
                    ):
                        raise VectorIndexMismatch(
                            f"vector {vid} has inconsistent embedding metadata"
                        )
                    if filter and not all(meta.get(k) == v for k, v in filter.items()):
                        continue
                    values = json.loads(vec_json)
                    self._validate_vector(values, dimension)
                    v = np.array(values, dtype=np.float32)
                    score = float(np.dot(q, v) / (q_norm * (np.linalg.norm(v) + 1e-8)))
                    results.append((vid, score, meta))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    async def delete(self, id: str) -> None:
        await self._ensure_init()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM vectors WHERE id = ?", (id,))
            await db.commit()

    async def replace_all(
        self, entries: list[tuple[str, list[float], dict]]
    ) -> None:
        await self._ensure_init()
        ids = [entry_id for entry_id, _vector, _metadata in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("vector replacement contains duplicate ids")

        replacement_dimension = self.embedding_dimension
        if entries and replacement_dimension is None:
            replacement_dimension = len(entries[0][1])
        for _entry_id, vector, _metadata in entries:
            self._validate_vector(vector, replacement_dimension)

        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute("BEGIN IMMEDIATE")
                current_metadata = await self._read_index_metadata(db)
                model = self.embedding_model or (
                    current_metadata[0] if current_metadata else "unspecified"
                )
                dimension = replacement_dimension or (
                    current_metadata[1] if current_metadata else None
                )
                if dimension is None:
                    raise ValueError(
                        "embedding dimension is required when replacing with an empty index"
                    )
                rows = [
                    (
                        entry_id,
                        json.dumps(vector),
                        json.dumps(
                            self._metadata_with_index(metadata, model, dimension)
                        ),
                    )
                    for entry_id, vector, metadata in entries
                ]
                await db.execute("DELETE FROM vectors")
                if rows:
                    await db.executemany(
                        "INSERT INTO vectors (id, vector, metadata) VALUES (?, ?, ?)",
                        rows,
                    )
                await db.execute(
                    "INSERT OR REPLACE INTO vector_index_metadata "
                    "(id, embedding_model, dimension) VALUES (1, ?, ?)",
                    (model, dimension),
                )
                async with db.execute("SELECT id FROM vectors") as cursor:
                    persisted_ids = {str(row[0]) for row in await cursor.fetchall()}
                if persisted_ids != set(ids):
                    raise RuntimeError("vector replacement verification failed")
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def index_info(self) -> Optional[VectorIndexInfo]:
        await self._ensure_init()
        async with aiosqlite.connect(self.db_path) as db:
            metadata = await self._read_index_metadata(db)
            count = await self._count(db)
        if metadata is None:
            if count:
                raise VectorIndexMismatch(
                    "vector index metadata is missing; rebuild the index"
                )
            return None
        self._assert_index_compatible(metadata)
        return VectorIndexInfo(
            model=metadata[0], dimension=metadata[1], count=count
        )

    async def delete_by_filter(self, filter: dict) -> None:
        """按 metadata 过滤级联删除（记忆/空间删除时清理向量）。"""
        await self._ensure_init()
        to_delete: list[str] = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id, metadata FROM vectors") as cursor:
                async for row in cursor:
                    vid, meta_json = row
                    meta = json.loads(meta_json)
                    if all(meta.get(k) == v for k, v in filter.items()):
                        to_delete.append(vid)
            for vid in to_delete:
                await db.execute("DELETE FROM vectors WHERE id = ?", (vid,))
            await db.commit()
