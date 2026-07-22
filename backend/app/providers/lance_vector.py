"""LanceDB vector and FTS retrieval with separate text/visual tables."""

from __future__ import annotations

import asyncio
import json
import math
import re
from pathlib import Path
from typing import Optional

import jieba
import lancedb
import pyarrow as pa
from lancedb.index import FTS

from app.providers.base import VectorIndexInfo, VectorIndexMismatch, VectorStore


_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", re.IGNORECASE)


def jieba_fts_text(text: str) -> str:
    """Pre-tokenize Chinese text for LanceDB FTS, then use whitespace tokenization."""
    raw = text.strip().lower()
    if not raw:
        return ""
    tokens: list[str] = []
    seen: set[str] = set()
    for token in jieba.lcut_for_search(raw):
        value = token.strip()
        if value and value not in seen:
            tokens.append(value)
            seen.add(value)
    for match in _IDENTIFIER_PATTERN.finditer(raw):
        value = match.group(0)
        if value and value not in seen:
            tokens.append(value)
            seen.add(value)
        for part in re.split(r"[-_]", value):
            if part and part not in seen:
                tokens.append(part)
                seen.add(part)
    return " ".join(tokens)


class LanceDBVectorStore(VectorStore):
    def __init__(
        self,
        db_path: str = "./data/lancedb",
        embedding_model: str | None = None,
        embedding_dimension: int | None = None,
        namespace: str = "text",
        enable_fts: bool = False,
    ):
        if not namespace or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
            for char in namespace
        ):
            raise ValueError("invalid vector namespace")
        self.db_path = Path(db_path)
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension
        self.namespace = namespace
        self.enable_fts = enable_fts
        self.table_name = f"{namespace}_vectors"
        self.db_path.mkdir(parents=True, exist_ok=True)

    @property
    def _metadata_path(self) -> Path:
        return self.db_path / f".{self.table_name}.metadata.json"

    def _schema(self, dimension: int) -> pa.Schema:
        return pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), dimension)),
                pa.field("content", pa.string()),
                pa.field("fts_text", pa.string()),
                pa.field("memory_id", pa.string()),
                pa.field("partition", pa.string()),
                pa.field("type", pa.string()),
                pa.field("media_path", pa.string()),
                pa.field("metadata_json", pa.string()),
                pa.field("embedding_model", pa.string()),
                pa.field("embedding_dimension", pa.int32()),
            ]
        )

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

    def _connect(self):
        return lancedb.connect(self.db_path)

    def _read_metadata(self) -> tuple[str, int] | None:
        if not self._metadata_path.exists():
            return None
        data = json.loads(self._metadata_path.read_text(encoding="utf-8"))
        return str(data["embedding_model"]), int(data["dimension"])

    def _write_metadata(self, model: str, dimension: int) -> None:
        self._metadata_path.write_text(
            json.dumps(
                {
                    "namespace": self.namespace,
                    "table": self.table_name,
                    "embedding_model": model,
                    "dimension": dimension,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

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

    def _table_exists(self, db) -> bool:
        return self.table_name in set(db.list_tables().tables)

    def _open_or_create_table(self, dimension: int):
        db = self._connect()
        if self._table_exists(db):
            return db.open_table(self.table_name)
        return db.create_table(self.table_name, schema=self._schema(dimension))

    @staticmethod
    def _sql_literal(value: object) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    def _where(self, filter: Optional[dict]) -> str | None:
        if not filter:
            return None
        allowed = {"id", "memory_id", "partition", "type", "media_path"}
        parts = []
        for key, value in filter.items():
            if key not in allowed:
                continue
            parts.append(f"{key} = {self._sql_literal(value)}")
        return " AND ".join(parts) if parts else None

    def _metadata_with_index(
        self, metadata: dict, model: str, dimension: int
    ) -> dict:
        return {
            **metadata,
            "embedding_namespace": self.namespace,
            "embedding_model": model,
            "embedding_dimension": dimension,
        }

    def _row(self, id: str, vector: list[float], metadata: dict) -> dict:
        index_metadata = self._read_metadata()
        vector_dimension = self._validate_vector(vector)
        if index_metadata is None:
            index_metadata = (
                self.embedding_model or "unspecified",
                self.embedding_dimension or vector_dimension,
            )
            self._write_metadata(*index_metadata)
        self._assert_index_compatible(index_metadata, vector_dimension)
        model, dimension = index_metadata
        indexed_metadata = self._metadata_with_index(metadata, model, dimension)
        content = str(metadata.get("content") or "")
        return {
            "id": id,
            "vector": [float(value) for value in vector],
            "content": content,
            "fts_text": jieba_fts_text(content),
            "memory_id": str(metadata.get("memory_id") or ""),
            "partition": str(metadata.get("partition") or ""),
            "type": str(metadata.get("type") or ""),
            "media_path": str(metadata.get("media_path") or ""),
            "metadata_json": json.dumps(indexed_metadata, ensure_ascii=False),
            "embedding_model": model,
            "embedding_dimension": dimension,
        }

    def _ensure_fts_index(self, table) -> None:
        if not self.enable_fts:
            return
        if table.count_rows() == 0:
            return
        table.create_index(
            "fts_text",
            config=FTS(
                base_tokenizer="whitespace",
                language="English",
                stem=False,
                remove_stop_words=False,
                ascii_folding=False,
            ),
            replace=True,
        )

    @staticmethod
    def _result_metadata(row: dict) -> dict:
        metadata = json.loads(row.get("metadata_json") or "{}")
        return metadata

    async def upsert(self, id: str, vector: list[float], metadata: dict) -> None:
        def _sync() -> None:
            row = self._row(id, vector, metadata)
            table = self._open_or_create_table(int(row["embedding_dimension"]))
            table.delete(f"id = {self._sql_literal(id)}")
            table.add([row])
            self._ensure_fts_index(table)

        await asyncio.to_thread(_sync)

    async def search(
        self, vector: list[float], top_k: int = 10, filter: Optional[dict] = None
    ) -> list[tuple[str, float, dict]]:
        vector_dimension = self._validate_vector(vector)

        def _sync() -> list[tuple[str, float, dict]]:
            index_metadata = self._read_metadata()
            db = self._connect()
            if index_metadata is None or not self._table_exists(db):
                return []
            self._assert_index_compatible(index_metadata, vector_dimension)
            table = db.open_table(self.table_name)
            query = (
                table.search(vector, vector_column_name="vector")
                .metric("cosine")
                .limit(top_k)
            )
            where = self._where(filter)
            if where:
                query = query.where(where, prefilter=True)
            rows = query.to_list()
            results = []
            for row in rows:
                distance = float(row.get("_distance", 1.0))
                score = max(-1.0, min(1.0, 1.0 - distance))
                results.append((str(row["id"]), score, self._result_metadata(row)))
            return results

        return await asyncio.to_thread(_sync)

    async def fts_search(
        self, query: str, top_k: int = 10, filter: Optional[dict] = None
    ) -> list[tuple[str, float, dict]]:
        if not self.enable_fts:
            raise NotImplementedError
        fts_query = jieba_fts_text(query)
        if not fts_query:
            return []

        def _sync() -> list[tuple[str, float, dict]]:
            index_metadata = self._read_metadata()
            db = self._connect()
            if index_metadata is None or not self._table_exists(db):
                return []
            self._assert_index_compatible(index_metadata)
            table = db.open_table(self.table_name)
            query_builder = table.search(
                fts_query, query_type="fts", fts_columns="fts_text"
            ).limit(top_k)
            where = self._where(filter)
            if where:
                query_builder = query_builder.where(where, prefilter=True)
            rows = query_builder.to_list()
            return [
                (
                    str(row["id"]),
                    float(row.get("_score", 0.0)),
                    self._result_metadata(row),
                )
                for row in rows
            ]

        return await asyncio.to_thread(_sync)

    async def delete(self, id: str) -> None:
        def _sync() -> None:
            db = self._connect()
            if not self._table_exists(db):
                return
            table = db.open_table(self.table_name)
            table.delete(f"id = {self._sql_literal(id)}")
            self._ensure_fts_index(table)

        await asyncio.to_thread(_sync)

    async def replace_all(
        self, entries: list[tuple[str, list[float], dict]]
    ) -> None:
        ids = [entry_id for entry_id, _vector, _metadata in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("vector replacement contains duplicate ids")

        replacement_dimension = self.embedding_dimension
        if entries and replacement_dimension is None:
            replacement_dimension = len(entries[0][1])
        if replacement_dimension is None:
            current = self._read_metadata()
            replacement_dimension = current[1] if current else None
        if replacement_dimension is None:
            raise ValueError(
                "embedding dimension is required when replacing with an empty index"
            )
        for _entry_id, vector, _metadata in entries:
            self._validate_vector(vector, replacement_dimension)

        def _sync() -> None:
            model = self.embedding_model or (
                self._read_metadata()[0] if self._read_metadata() else "unspecified"
            )
            self._write_metadata(model, int(replacement_dimension))
            db = self._connect()
            if self._table_exists(db):
                db.drop_table(self.table_name)
            table = db.create_table(
                self.table_name, schema=self._schema(int(replacement_dimension))
            )
            rows = [self._row(entry_id, vector, metadata) for entry_id, vector, metadata in entries]
            if rows:
                table.add(rows)
            self._ensure_fts_index(table)
            persisted_ids = {
                str(row["id"])
                for row in table.search().limit(max(len(rows), 1)).to_list()
            } if rows else set()
            if persisted_ids != set(ids):
                raise RuntimeError("vector replacement verification failed")

        await asyncio.to_thread(_sync)

    async def index_info(self) -> Optional[VectorIndexInfo]:
        def _sync() -> Optional[VectorIndexInfo]:
            metadata = self._read_metadata()
            db = self._connect()
            if metadata is None:
                if self._table_exists(db) and db.open_table(self.table_name).count_rows():
                    raise VectorIndexMismatch(
                        "vector index metadata is missing; rebuild the index"
                    )
                return None
            self._assert_index_compatible(metadata)
            count = (
                db.open_table(self.table_name).count_rows()
                if self._table_exists(db)
                else 0
            )
            return VectorIndexInfo(model=metadata[0], dimension=metadata[1], count=count)

        return await asyncio.to_thread(_sync)

    async def delete_by_filter(self, filter: dict) -> None:
        where = self._where(filter)
        if not where:
            return

        def _sync() -> None:
            db = self._connect()
            if not self._table_exists(db):
                return
            table = db.open_table(self.table_name)
            table.delete(where)
            self._ensure_fts_index(table)

        await asyncio.to_thread(_sync)
