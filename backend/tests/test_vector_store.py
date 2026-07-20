import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.providers.base import VectorIndexMismatch
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


@pytest.mark.asyncio
async def test_replace_all_removes_stale_vectors_atomically():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteVectorStore(str(Path(tmp) / "vec.db"))
        await store.upsert("old", [1.0, 0.0], {"partition": "work"})
        await store.replace_all(
            [("new", [0.0, 1.0, 0.0], {"partition": "work"})]
        )
        results = await store.search([0.0, 1.0, 0.0], top_k=10)
        assert [result[0] for result in results] == ["new"]
        assert results[0][2]["embedding_dimension"] == 3
        info = await store.index_info()
        assert info is not None
        assert (info.model, info.dimension, info.count) == ("unspecified", 3, 1)


@pytest.mark.asyncio
async def test_replace_all_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteVectorStore(
            str(Path(tmp) / "vec.db"), "qwen3-embedding:0.6b-q4_k_m", 3
        )
        entries = [("a", [1.0, 0.0, 0.0], {"partition": "work"})]

        await store.replace_all(entries)
        await store.replace_all(entries)

        info = await store.index_info()
        assert info is not None and info.count == 1
        assert [row[0] for row in await store.search(entries[0][1])] == ["a"]


@pytest.mark.asyncio
async def test_failed_replacement_preserves_previous_index():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteVectorStore(
            str(Path(tmp) / "vec.db"), "qwen3-embedding:0.6b-q4_k_m", 2
        )
        await store.upsert("old", [1.0, 0.0], {"partition": "work"})

        with pytest.raises(VectorIndexMismatch, match="dimension mismatch"):
            await store.replace_all(
                [("new", [0.0, 1.0, 0.0], {"partition": "work"})]
            )

        assert [row[0] for row in await store.search([1.0, 0.0])] == ["old"]


@pytest.mark.asyncio
async def test_transaction_failure_rolls_back_deleted_vectors():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "vec.db"
        store = SqliteVectorStore(
            str(db_path), "qwen3-embedding:0.6b-q4_k_m", 2
        )
        await store.upsert("old", [1.0, 0.0], {"partition": "work"})
        with sqlite3.connect(db_path) as db:
            db.execute(
                "CREATE TRIGGER reject_new BEFORE INSERT ON vectors "
                "WHEN NEW.id = 'new' BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
            )

        with pytest.raises(sqlite3.IntegrityError, match="forced failure"):
            await store.replace_all(
                [("new", [0.0, 1.0], {"partition": "work"})]
            )

        assert [row[0] for row in await store.search([1.0, 0.0])] == ["old"]


@pytest.mark.asyncio
async def test_configured_model_must_match_persisted_index():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "vec.db")
        old_store = SqliteVectorStore(db_path, "nomic-embed-text:latest", 2)
        await old_store.upsert("old", [1.0, 0.0], {"partition": "work"})

        qwen_store = SqliteVectorStore(
            db_path, "qwen3-embedding:0.6b-q4_k_m", 2
        )
        with pytest.raises(VectorIndexMismatch, match="model mismatch"):
            await qwen_store.search([1.0, 0.0])


@pytest.mark.asyncio
async def test_legacy_index_without_metadata_requires_rebuild():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "vec.db"
        with sqlite3.connect(db_path) as db:
            db.execute(
                "CREATE TABLE vectors "
                "(id TEXT PRIMARY KEY, vector TEXT NOT NULL, metadata TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO vectors (id, vector, metadata) VALUES (?, ?, ?)",
                ("legacy", json.dumps([1.0, 0.0]), json.dumps({"partition": "work"})),
            )

        store = SqliteVectorStore(
            str(db_path), "qwen3-embedding:0.6b-q4_k_m", 2
        )
        with pytest.raises(VectorIndexMismatch, match="metadata is missing"):
            await store.search([1.0, 0.0])
