from __future__ import annotations

import argparse
import asyncio
import math
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.providers import get_provider_factory, get_settings
from app.repositories.database import async_session_factory
from app.repositories.memory_repo import MemoryRepository


@dataclass(frozen=True)
class RebuildResult:
    rebuilt: int
    skipped: int
    model: str
    dimension: int
    backup_path: Path | None = None


def backup_vector_database(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = db_path.with_name(f"{db_path.name}.bak.{timestamp}")
    with sqlite3.connect(db_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return backup_path


async def rebuild(dry_run: bool = False) -> RebuildResult:
    settings = get_settings()
    if not dry_run and settings.provider_mode.lower() != "local":
        raise RuntimeError("vector rebuild requires ECHO_PROVIDER_MODE=local")
    providers = get_provider_factory() if not dry_run else None
    embedding = providers.embedding() if providers else None
    vector_store = providers.vector_store() if providers else None
    rebuilt = 0
    skipped = 0
    entries: list[tuple[str, list[float], dict]] = []

    async with async_session_factory() as db:
        repo = MemoryRepository(db)
        for evidence in await repo.list_all_evidences():
            content = evidence.content.strip()
            memory = await repo.get_time_memory(evidence.memory_id)
            if not content or memory is None:
                skipped += 1
                continue
            if not dry_run:
                assert embedding is not None
                result = await embedding.embed_document(content)
                if len(result.vector) != settings.embedding_dimension:
                    raise RuntimeError(
                        f"evidence {evidence.id} returned {len(result.vector)} dimensions; "
                        f"expected {settings.embedding_dimension}"
                    )
                if not all(math.isfinite(value) for value in result.vector):
                    raise RuntimeError(
                        f"evidence {evidence.id} returned a non-finite vector"
                    )
                entries.append(
                    (
                        str(evidence.id),
                        result.vector,
                        {
                            "memory_id": str(evidence.memory_id),
                            "partition": memory.partition.value,
                            "type": evidence.type.value,
                        },
                    )
                )
            rebuilt += 1
    backup_path = None
    if not dry_run:
        assert vector_store is not None
        backup_path = backup_vector_database(Path(settings.vector_db_path).resolve())
        await vector_store.replace_all(entries)
        info = await vector_store.index_info()
        if (
            info is None
            or info.model != settings.embedding_model
            or info.dimension != settings.embedding_dimension
            or info.count != rebuilt
        ):
            raise RuntimeError("rebuilt vector index failed post-write verification")
    return RebuildResult(
        rebuilt=rebuilt,
        skipped=skipped,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
        backup_path=backup_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild Evidence vectors with the configured document embedding task."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Count eligible Evidence rows without writing vectors."
    )
    args = parser.parse_args()
    result = asyncio.run(rebuild(dry_run=args.dry_run))
    print(
        f"rebuilt={result.rebuilt} skipped={result.skipped} "
        f"model={result.model} dimension={result.dimension} "
        f"backup={result.backup_path or '-'} dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    main()
