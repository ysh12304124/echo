import tempfile
from pathlib import Path

import pytest

from app.providers.base import VectorIndexMismatch
from app.providers.lance_vector import LanceDBVectorStore, jieba_fts_text


@pytest.mark.asyncio
async def test_lancedb_upsert_vector_search_and_filter():
    with tempfile.TemporaryDirectory() as tmp:
        store = LanceDBVectorStore(str(Path(tmp) / "lance"), "qwen", 3)
        await store.upsert(
            "a",
            [1.0, 0.0, 0.0],
            {"memory_id": "m1", "partition": "work", "content": "张经理交付样品"},
        )
        await store.upsert(
            "b",
            [0.0, 1.0, 0.0],
            {"memory_id": "m2", "partition": "work", "content": "讨论会议安排"},
        )
        await store.upsert(
            "c",
            [1.0, 0.1, 0.0],
            {"memory_id": "m3", "partition": "quality_time", "content": "家庭照片"},
        )

        results = await store.search([1.0, 0.0, 0.0], top_k=3)
        assert results[0][0] == "a"
        assert results[0][1] > results[1][1]

        work_only = await store.search(
            [1.0, 0.0, 0.0], top_k=10, filter={"partition": "work"}
        )
        assert {result[0] for result in work_only} == {"a", "b"}


@pytest.mark.asyncio
async def test_lancedb_fts_uses_jieba_preprocessed_bm25_terms():
    with tempfile.TemporaryDirectory() as tmp:
        store = LanceDBVectorStore(
            str(Path(tmp) / "lance"), "qwen", 3, namespace="text", enable_fts=True
        )
        await store.replace_all(
            [
                (
                    "irrelevant",
                    [0.0, 1.0, 0.0],
                    {"partition": "work", "content": "讨论下周会议安排"},
                ),
                (
                    "relevant",
                    [1.0, 0.0, 0.0],
                    {"partition": "work", "content": "张经理下周三交付样品"},
                ),
                (
                    "partial",
                    [0.9, 0.1, 0.0],
                    {"partition": "work", "content": "张经理下周三参加会议"},
                ),
            ]
        )

        assert "交付" in jieba_fts_text("张经理什么时候交付样品")
        results = await store.fts_search(
            "张经理什么时候交付样品", top_k=3, filter={"partition": "work"}
        )
        assert results[0][0] == "relevant"
        assert results[0][1] > 0


@pytest.mark.asyncio
async def test_lancedb_replace_all_is_idempotent_and_validates_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        store = LanceDBVectorStore(str(Path(tmp) / "lance"), "qwen", 2)
        entries = [("a", [1.0, 0.0], {"partition": "work", "content": "样品"})]

        await store.replace_all(entries)
        await store.replace_all(entries)

        info = await store.index_info()
        assert info is not None
        assert (info.model, info.dimension, info.count) == ("qwen", 2, 1)
        assert [row[0] for row in await store.search([1.0, 0.0])] == ["a"]

        mismatched = LanceDBVectorStore(str(Path(tmp) / "lance"), "other", 2)
        with pytest.raises(VectorIndexMismatch, match="model mismatch"):
            await mismatched.search([1.0, 0.0])


@pytest.mark.asyncio
async def test_lancedb_text_and_visual_tables_are_isolated():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "lance")
        text_store = LanceDBVectorStore(db_path, "qwen", 2, namespace="text", enable_fts=True)
        visual_store = LanceDBVectorStore(db_path, "clip", 3, namespace="visual")

        await text_store.replace_all(
            [("text-1", [1.0, 0.0], {"partition": "work", "content": "文本证据"})]
        )
        await visual_store.replace_all(
            [("image-1", [0.0, 1.0, 0.0], {"partition": "work", "content": "关键帧"})]
        )
        await visual_store.replace_all(
            [("image-2", [0.0, 0.0, 1.0], {"partition": "work", "content": "新关键帧"})]
        )

        assert [row[0] for row in await text_store.search([1.0, 0.0])] == ["text-1"]
        assert [row[0] for row in await visual_store.search([0.0, 0.0, 1.0])] == [
            "image-2"
        ]
        assert (await text_store.index_info()).count == 1
        assert (await visual_store.index_info()).count == 1
