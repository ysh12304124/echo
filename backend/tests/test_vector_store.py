import tempfile
from pathlib import Path

import pytest

from app.providers.sqlite_vector import SqliteVectorStore


@pytest.mark.asyncio
async def test_upsert_search_and_filter():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteVectorStore(str(Path(tmp) / "vec.db"))
        await store.upsert("a", [1.0, 0.0, 0.0], {"memory_id": "m1", "partition": "work"})
        await store.upsert("b", [0.0, 1.0, 0.0], {"memory_id": "m2", "partition": "work"})
        await store.upsert("c", [1.0, 0.1, 0.0], {"memory_id": "m3", "partition": "quality_time"})

        # 最相似应为 a，其次 c
        results = await store.search([1.0, 0.0, 0.0], top_k=3)
        assert results[0][0] == "a"
        assert results[0][1] > results[1][1]

        # metadata 过滤（分区隔离）
        work_only = await store.search([1.0, 0.0, 0.0], top_k=10, filter={"partition": "work"})
        assert {r[0] for r in work_only} == {"a", "b"}


@pytest.mark.asyncio
async def test_persistence_across_instances():
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "vec.db")
        store1 = SqliteVectorStore(db)
        await store1.upsert("x", [0.5, 0.5], {"memory_id": "m1"})

        store2 = SqliteVectorStore(db)
        results = await store2.search([0.5, 0.5], top_k=1)
        assert results and results[0][0] == "x"


@pytest.mark.asyncio
async def test_delete_and_delete_by_filter():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteVectorStore(str(Path(tmp) / "vec.db"))
        await store.upsert("a", [1.0, 0.0], {"memory_id": "m1"})
        await store.upsert("b", [0.0, 1.0], {"memory_id": "m1"})
        await store.upsert("c", [1.0, 1.0], {"memory_id": "m2"})

        await store.delete("a")
        assert {r[0] for r in await store.search([1.0, 1.0], top_k=10)} == {"b", "c"}

        await store.delete_by_filter({"memory_id": "m1"})
        remaining = {r[0] for r in await store.search([1.0, 1.0], top_k=10)}
        assert remaining == {"c"}
