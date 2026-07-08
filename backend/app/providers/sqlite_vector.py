"""持久化向量检索：向量存 SQLite，加载入 numpy 做余弦相似度 + metadata 过滤。

MVP 规模下（单机、万级向量）足够；避免引入 FAISS 等重依赖。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import aiosqlite
import numpy as np

from app.providers.base import VectorStore


class SqliteVectorStore(VectorStore):
    def __init__(self, db_path: str = "./data/vectors.db"):
        self.db_path = db_path
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
            await db.commit()
        self._initialized = True

    async def upsert(self, id: str, vector: list[float], metadata: dict) -> None:
        await self._ensure_init()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO vectors (id, vector, metadata) VALUES (?, ?, ?)",
                (id, json.dumps(vector), json.dumps(metadata)),
            )
            await db.commit()

    async def search(
        self, vector: list[float], top_k: int = 10, filter: Optional[dict] = None
    ) -> list[tuple[str, float, dict]]:
        await self._ensure_init()
        q = np.array(vector, dtype=np.float32)
        q_norm = np.linalg.norm(q) + 1e-8
        results: list[tuple[str, float, dict]] = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id, vector, metadata FROM vectors") as cursor:
                async for row in cursor:
                    vid, vec_json, meta_json = row
                    meta = json.loads(meta_json)
                    if filter and not all(meta.get(k) == v for k, v in filter.items()):
                        continue
                    v = np.array(json.loads(vec_json), dtype=np.float32)
                    score = float(np.dot(q, v) / (q_norm * (np.linalg.norm(v) + 1e-8)))
                    results.append((vid, score, meta))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    async def delete(self, id: str) -> None:
        await self._ensure_init()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM vectors WHERE id = ?", (id,))
            await db.commit()

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
