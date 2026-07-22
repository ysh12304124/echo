from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.providers import get_provider_factory, get_settings
from app.repositories.database import async_session_factory
from app.repositories.memory_repo import MemoryRepository
from app.services.keyframe_index import build_keyframe_entries
from scripts.rebuild_evidence_vectors import backup_vector_store_path


async def rebuild(dry_run: bool = False) -> tuple[int, int, Path | None]:
    settings = get_settings()
    providers = get_provider_factory()
    async with async_session_factory() as db:
        memories, _ = await MemoryRepository(db).list_time_memories(limit=1_000_000)
    if dry_run:
        count = sum(len(memory.key_frames) for memory in memories)
        return count, 0, None

    entries, skipped = await build_keyframe_entries(memories, providers)
    backup = backup_vector_store_path(Path(settings.lance_db_path).resolve())
    store = providers.visual_vector_store()
    await store.replace_all(entries)
    info = await store.index_info()
    if (
        info is None
        or info.model != settings.visual_embedding_model
        or info.dimension != settings.visual_embedding_dimension
        or info.count != len(entries)
    ):
        raise RuntimeError("rebuilt visual vector index failed verification")
    return len(entries), skipped, backup


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild keyframe image vectors")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    rebuilt, skipped, backup = asyncio.run(rebuild(args.dry_run))
    print(
        f"rebuilt={rebuilt} skipped={skipped} "
        f"backup={backup or '-'} dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    main()
